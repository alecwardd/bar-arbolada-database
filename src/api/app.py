"""FastAPI entry point for the Sites manager dashboard."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from contextlib import asynccontextmanager
import logging
import os
from datetime import date
from threading import Lock
from typing import Callable, Literal, TypeVar

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.middleware.trustedhost import TrustedHostMiddleware

from src.config import get_session

from . import services
from .auth import require_manager_token
from .schemas import (
    DailySalesResponse,
    HealthResponse,
    ImportOperationsResponse,
    InventoryHealthResponse,
    OverviewResponse,
    ProfitabilityResponse,
    ReadinessResponse,
    StaffingRushResponse,
)


logger = logging.getLogger(__name__)
T = TypeVar("T")
DEFAULT_READINESS_TIMEOUT_SECONDS = 2.0
MIN_READINESS_TIMEOUT_SECONDS = 0.05
MAX_READINESS_TIMEOUT_SECONDS = 5.0
READINESS_STATEMENT_TIMEOUT_MS = 1_500


def _readiness_timeout_seconds() -> float:
    """Return a tightly bounded readiness deadline.

    The upper bound is intentional: an operator typo must not turn readiness
    into an unbounded database wait.
    """

    raw = os.getenv(
        "MANAGER_API_READINESS_TIMEOUT_SECONDS",
        str(DEFAULT_READINESS_TIMEOUT_SECONDS),
    )
    try:
        configured = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_READINESS_TIMEOUT_SECONDS
    return min(
        MAX_READINESS_TIMEOUT_SECONDS,
        max(MIN_READINESS_TIMEOUT_SECONDS, configured),
    )


def _probe_database() -> None:
    """Perform the smallest useful read-only PostgreSQL probe.

    The transaction and statement timeout are defense in depth. The production
    launcher also sets libpq connection and session timeouts before importing
    the application.
    """

    session = get_session()
    try:
        session.execute(text("SET TRANSACTION READ ONLY"))
        session.execute(
            text(
                "SET LOCAL statement_timeout = "
                f"'{READINESS_STATEMENT_TIMEOUT_MS}ms'"
            )
        )
        session.execute(text("SELECT 1"))
    finally:
        session.rollback()
        session.close()


class _DatabaseReadiness:
    """Serialize probes and return within a fixed wall-clock deadline."""

    def __init__(self, probe: Callable[[], None], timeout_seconds: float):
        self._probe = probe
        self._timeout_seconds = timeout_seconds
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="manager-db-readiness",
        )
        self._lock = Lock()
        self._future: Future[None] | None = None

    def check(self) -> bool:
        with self._lock:
            if self._future is None or self._future.done():
                self._future = self._executor.submit(self._probe)
            future = self._future

        try:
            future.result(timeout=self._timeout_seconds)
        except TimeoutError:
            return False
        except Exception:
            logger.warning("Manager API database readiness probe failed")
            return False
        return True

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


def _allowed_origins() -> list[str]:
    raw = os.getenv("MANAGER_API_ALLOWED_ORIGINS", "")
    origins = []
    for item in raw.split(","):
        origin = item.strip().rstrip("/")
        if origin.startswith("https://") or origin.startswith("http://localhost:"):
            origins.append(origin)
    return sorted(set(origins))


def _data_call(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except services.InvalidPeriod as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from None
    except HTTPException:
        raise
    except Exception:
        logger.error("Manager API data operation failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Manager data is temporarily unavailable.",
        ) from None


def create_app() -> FastAPI:
    database_readiness = _DatabaseReadiness(
        _probe_database,
        _readiness_timeout_seconds(),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            yield
        finally:
            database_readiness.close()

    docs_enabled = os.getenv("MANAGER_API_ENABLE_DOCS", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    app = FastAPI(
        title="Bar Arbolada Manager API",
        version="1.0.0",
        description="Read-only, redacted analytics API for the manager dashboard.",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        lifespan=lifespan,
    )
    app.state.database_readiness = database_readiness

    allowed_hosts = [
        host.strip()
        for host in os.getenv(
            "MANAGER_API_ALLOWED_HOSTS",
            "127.0.0.1,localhost,testserver",
        ).split(",")
        if host.strip()
    ]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    origins = _allowed_origins()
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.middleware("http")
    async def protect_manager_responses(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/v1/") or request.url.path in {
            "/health",
            "/ready",
        }:
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["Pragma"] = "no-cache"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        """Liveness only; does not query or disclose database state."""

        return HealthResponse(status="ok")

    @app.get(
        "/ready",
        response_model=ReadinessResponse,
        tags=["system"],
        responses={
            status.HTTP_503_SERVICE_UNAVAILABLE: {
                "model": ReadinessResponse,
                "description": "Database unavailable within the fixed deadline.",
            }
        },
    )
    def ready(response: Response) -> ReadinessResponse:
        """Bounded database readiness with no diagnostic disclosure."""

        if not database_readiness.check():
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return ReadinessResponse(status="unavailable")
        return ReadinessResponse(status="ready")

    router = APIRouter(
        prefix="/api/v1",
        dependencies=[Depends(require_manager_token)],
    )

    @router.get("/overview", response_model=OverviewResponse, tags=["manager"])
    def overview(
        start: date | None = Query(default=None),
        end: date | None = Query(default=None),
        preset: Literal["30d", "60d", "90d", "ytd"] = Query(default="30d"),
    ) -> OverviewResponse:
        """Executive period, KPI, sales, sanitized P&L, and reorder summary.

        Explicit ``start`` takes precedence over ``preset``. Presets are
        bounded to the first available sales date.
        """

        bounds = _data_call(lambda: services.resolve_period(start, end, preset))
        return _data_call(lambda: services.build_overview(bounds))

    @router.get("/daily-sales", response_model=DailySalesResponse, tags=["manager"])
    def daily_sales(
        start: date | None = Query(default=None),
        end: date | None = Query(default=None),
    ) -> DailySalesResponse:
        """Bounded daily sales series and aggregate totals."""

        bounds = _data_call(lambda: services.resolve_period(start, end))
        return _data_call(lambda: services.build_daily_sales(bounds.period))

    @router.get("/staffing-rush", response_model=StaffingRushResponse, tags=["manager"])
    def staffing_rush(
        start: date | None = Query(default=None),
        end: date | None = Query(default=None),
    ) -> StaffingRushResponse:
        """Aggregate staffing efficiency and rush heatmap without employee identity."""

        bounds = _data_call(lambda: services.resolve_period(start, end))
        return _data_call(lambda: services.build_staffing_rush(bounds.period))

    @router.get("/profitability", response_model=ProfitabilityResponse, tags=["manager"])
    def profitability(
        start: date | None = Query(default=None),
        end: date | None = Query(default=None),
    ) -> ProfitabilityResponse:
        """Sanitized P&L, category profitability, and cost-data coverage."""

        bounds = _data_call(lambda: services.resolve_period(start, end))
        return _data_call(lambda: services.build_profitability(bounds.period))

    @router.get("/inventory/health", response_model=InventoryHealthResponse, tags=["manager"])
    def inventory_health(
        as_of: date | None = Query(default=None),
        limit: int = Query(default=200, ge=1, le=500),
    ) -> InventoryHealthResponse:
        """Ledger-backed inventory health using closing_qty as on-hand truth."""

        return _data_call(lambda: services.build_inventory_health(as_of, limit))

    @router.get(
        "/import-operations",
        response_model=ImportOperationsResponse,
        tags=["manager"],
    )
    def import_operations(
        limit: int = Query(default=25, ge=1, le=100),
    ) -> ImportOperationsResponse:
        """Latest import health and redacted log summaries."""

        return _data_call(lambda: services.build_import_operations(limit))

    app.include_router(router)
    return app


app = create_app()
