"""Planted fixture: three kinds of comment drift (SDS-S-095)."""


def load_order(order_id, *, fresh=False):
    """Load one order.

    Args:
        order_id: the order to load
        fresh: bypass the cache
        timeout: seconds to wait — REMOVED two releases ago; documented parameter is stale
    """
    return {"id": order_id, "fresh": fresh}


def total(rows):
    # uses normalize_rows() to coerce quantities first — that helper was deleted
    return sum(r["qty"] * r["price"] for r in rows)


def legacy_path():
    # old implementation kept for reference:

    # rows = fetch_all()
    # for r in rows:
    #     r["qty"] = int(r["qty"])
    # return rows
    return []
