"""FastAPI entry point for the Sites manager dashboard."""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import Callable, Literal, TypeVar

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import services
from .auth import require_manager_token
from .schemas import (
    DailySalesResponse,
    HealthResponse,
    ImportOperationsResponse,
    InventoryHealthResponse,
    OverviewResponse,
    ProfitabilityResponse,
    StaffingRushResponse,
)


logger = logging.getLogger(__name__)
T = TypeVar("T")


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
    )

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
        if request.url.path.startswith("/api/v1/"):
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["Pragma"] = "no-cache"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        """Liveness only; does not query or disclose database state."""

        return HealthResponse(status="ok")

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
