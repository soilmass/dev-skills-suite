"""Planted fixture: an oversized module with two independent clusters.

Cluster A (orders): OrderLine, load_order, total_for reference each other.
Cluster B (reporting): Report, format_row, render_report, _pad reference
each other. Neither cluster names the other, so the seam is mechanical.
"""

TAX_RATE = 0.2
COLUMNS = ("sku", "qty", "total")


class OrderLine:
    def __init__(self, sku, qty, unit_price):
        self.sku = sku
        self.qty = qty
        self.unit_price = unit_price

    def subtotal(self):
        return self.qty * self.unit_price


def load_order(order_id):
    return [OrderLine("sku-" + str(order_id), 2, 10.0)]


def total_for(order_id, tax_rate=TAX_RATE):
    lines = load_order(order_id)
    return sum(line.subtotal() for line in lines) * (1 + tax_rate)


class Report:
    def __init__(self, title):
        self.title = title
        self.rows = []

    def add(self, row):
        self.rows.append(row)


def format_row(values):
    return " | ".join(_pad(str(v), 8) for v in values)


def render_report(report):
    if not isinstance(report, Report):
        raise TypeError("expected a Report")
    out = [report.title, format_row(COLUMNS)]
    for row in report.rows:
        out.append(format_row(row))
    return "\n".join(out)


def _pad(text, width):
    return text.ljust(width)
