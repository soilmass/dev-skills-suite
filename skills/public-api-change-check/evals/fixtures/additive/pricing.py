"""Additive surface: old plus refund."""


def price(order, *, currency="USD", discount=0.0) -> float:
    return 0.0


def legacy_total(order):
    return 0


def refund(order):
    return 0.0


def _internal():
    return None


class Cart:
    TAX = 0.2

    def __init__(self, items=None):
        self.items = items or []

    def add(self, item, qty=1):
        self.items.append((item, qty))

    def clear(self):
        self.items = []
