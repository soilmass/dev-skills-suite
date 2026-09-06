"""Planted fixture: consistent with the dominant conventions; must draw no finding."""

RETRY_DELAY = 1.5


class Customer:
    def __init__(self, customer_id):
        self.customer_id = customer_id


def find_customer(customer_id, include_archived=False):
    return Customer(customer_id) if include_archived or customer_id else None


def _private_helper(raw_value):
    return raw_value
