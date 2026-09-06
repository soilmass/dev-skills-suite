"""Planted fixture: a snake_case module with one deviant of each kind.

Dominant: functions snake_case (4 vs 1), classes CapWords (2 vs 1),
constants UPPER_CASE (3 vs 1), arguments snake_case.
"""

MAX_RETRIES = 3
DEFAULT_CURRENCY = "USD"
TAX_RATE = 0.2
default_limit = 50  # planted: snake_case constant among UPPER_CASE ones


class OrderLine:
    def __init__(self, sku, qty):
        self.sku = sku
        self.qty = qty


class Invoice:
    pass


class order_batch:  # planted: snake_case class among CapWords ones
    pass


def load_order(order_id, fresh=False):
    return {"id": order_id, "fresh": fresh}


def total_for(order_lines, tax_rate=TAX_RATE):
    return sum(l.qty for l in order_lines) * (1 + tax_rate)


def fetchOrders(customerId):  # planted: camelCase function and argument
    return [load_order(customerId)]


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def f(x, y):  # planted: ambiguous short names
    return x + y


squares = [n * n for n in range(10)]
double = lambda v: v * 2
