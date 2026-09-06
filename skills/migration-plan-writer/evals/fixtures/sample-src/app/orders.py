"""Planted fixture: three call sites of the old path."""
from legacy import legacy_fetch


def load_order(order_id):
    return legacy_fetch(f"/orders/{order_id}")


def load_orders(ids):
    return [legacy_fetch(f"/orders/{i}") for i in ids]


def refresh(order_id):
    data = legacy_fetch(f"/orders/{order_id}?fresh=1")
    return data
