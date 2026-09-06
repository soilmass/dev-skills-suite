"""Proposed surface: one instance of each change."""


def price(order, *, currency="EUR", discount) -> float:
    return 0.0


def refund(order):
    return 0.0


def _internal():
    return None


class Cart:
    TAX = 0.2

    def __init__(self, items=None):
        self.items = items or []

    def add(self, item, quantity=1):
        self.items.append((item, quantity))
