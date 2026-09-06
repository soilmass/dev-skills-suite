"""Planted fixture: load_order and Cart.add are covered; cancel_order,
_audit and Cart.clear are not; __repr__ is uncovered but skipped."""


def load_order(order_id):
    return {"id": order_id}


def cancel_order(order_id):
    order = load_order(order_id)
    order["cancelled"] = True
    return order


def _audit(order):
    return order


class Cart:
    def __init__(self):
        self.items = []

    def add(self, item):
        self.items.append(item)

    def clear(self):
        self.items = []

    def __repr__(self):
        return f"Cart({self.items})"
