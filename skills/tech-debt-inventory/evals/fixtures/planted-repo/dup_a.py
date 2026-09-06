"""Planted fixture: shares an 8-line block with dup_b.py (SDS-S-095)."""


def normalize_order(order):
    items = []
    for raw in order.get("items", []):
        sku = raw["sku"].strip().upper()
        qty = int(raw.get("qty", 1))
        if qty <= 0:
            continue
        price = round(float(raw["price"]), 2)
        items.append({"sku": sku, "qty": qty, "price": price})
    return {"id": order["id"], "items": items}


def order_total(order):
    return sum(i["qty"] * i["price"] for i in order["items"])
