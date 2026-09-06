"""Planted fixture: one call site of the old path."""
from legacy import legacy_fetch


def monthly_report(month):
    rows = legacy_fetch(f"/reports/{month}")
    return sum(r["total"] for r in rows)
