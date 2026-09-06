"""Planted fixture: the same 8-line normalization block as dup_a.py."""


def normalize_quote(order):
    items = []
    for raw in order.get("items", []):
        sku = raw["sku"].strip().upper()
        qty = int(raw.get("qty", 1))
        if qty <= 0:
            continue
        price = round(float(raw["price"]), 2)
        items.append({"sku": sku, "qty": qty, "price": price})
    return {"id": order["id"], "items": items, "expires": order.get("expires")}
