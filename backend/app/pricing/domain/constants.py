"""Horizon and occupancy window (design D18).

These are PRD figures (§8.3 and §7.17), not operational levers: changing either changes
what the system promises, and that gets reviewed in a Pull Request, not in a `.env`. That
is why they are module constants and not `Settings` fields — and why this change adds no
environment variable at all.

Both spans start on the day **after** the execution date and are half-open on the right, so
day 1 of the horizon is tomorrow and `days_before` never reaches 0. That is design D5's
wording for the occupancy window — "los 30 días naturales siguientes a la fecha de
ejecución" — applied to both, so the two never disagree about which day is the first.
"""

#: Days of the generated horizon: [execution_date + 1, execution_date + 61) (PRD §8.3).
HORIZON_DAYS = 60

#: Days the occupancy is measured over: [execution_date + 1, execution_date + 31) (PRD §7.17).
OCCUPANCY_WINDOW_DAYS = 30
