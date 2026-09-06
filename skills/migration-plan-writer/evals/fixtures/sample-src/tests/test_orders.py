"""Planted fixture: a test that references the old path (migrated last)."""
from unittest.mock import patch


def test_load_order_uses_legacy_fetch():
    with patch("app.orders.legacy_fetch") as fetch:
        fetch.return_value = {"id": 1}
        from app.orders import load_order
        assert load_order(1) == {"id": 1}
