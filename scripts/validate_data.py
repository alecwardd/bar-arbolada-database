"""Quick data validation after import."""
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent))

from src.config import get_session
from src.models import *
from sqlalchemy import func

s = get_session()

# Summary counts
tables = [
    ('import_logs', ImportLog),
    ('pos_daily_sales', PosDailySales),
    ('pos_daily_sales_by_daypart', PosDailySalesByDaypart),
    ('pos_daily_sales_by_category', PosDailySalesByCategory),
    ('pos_hourly_sales', PosHourlySales),
    ('pos_checks', PosCheck),
    ('pos_product_mix', PosProductMix),
    ('pos_comps', PosComp),
    ('pos_voids', PosVoid),
    ('pos_payments', PosPayment),
    ('pos_labor', PosLabor),
]

print('=' * 55)
hdr = 'TABLE'
print(f'{hdr:<35} {"ROWS":>10}')
print('=' * 55)
for name, model in tables:
    count = s.query(func.count(model.id)).scalar()
    print(f'{name:<35} {count:>10,}')
print('=' * 55)

# Date ranges
print('\nDATE COVERAGE:')
for name, model, field in [
    ('daily_sales', PosDailySales, PosDailySales.trading_day),
    ('hourly_sales', PosHourlySales, PosHourlySales.trading_day),
    ('checks', PosCheck, PosCheck.trading_day),
    ('labor', PosLabor, PosLabor.shift_date),
    ('payments', PosPayment, PosPayment.trading_day),
]:
    mn = s.query(func.min(field)).scalar()
    mx = s.query(func.max(field)).scalar()
    days = s.query(func.count(func.distinct(field))).scalar()
    print(f'  {name:<20} {mn} to {mx} ({days} unique days)')

# Spot check: total net sales from daily_sales
total_net = s.query(func.sum(PosDailySales.net_sales)).scalar()
print(f'\nTOTAL NET SALES (pos_daily_sales): ${total_net:,.2f}' if total_net else '\nNo net sales data')

# Check for days with only partial data (from multi-day import)
partial_days = s.query(PosDailySales).filter(
    PosDailySales.net_sales.is_(None),
    PosDailySales.total_checks.isnot(None),
).count()
print(f'Days with check data only (from multi-day reports): {partial_days}')

# Unique employees in labor
emp_count = s.query(
    func.count(func.distinct(
        func.concat(PosLabor.first_name, ' ', PosLabor.last_name)
    ))
).scalar()
print(f'Unique employees in labor data: {emp_count}')

# Import log summary
print('\nIMPORT LOG SUMMARY:')
for status, cnt in s.query(ImportLog.status, func.count(ImportLog.id)).group_by(ImportLog.status).all():
    print(f'  {status}: {cnt}')

s.close()
