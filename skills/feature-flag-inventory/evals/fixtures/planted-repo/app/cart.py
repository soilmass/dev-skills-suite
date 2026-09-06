"""Planted fixture: a second module checking the rolled-out flag and a young one."""
import flags


def total(cart):
    if flags.is_enabled("new-checkout"):
        return sum(cart)
    if flags.feature_enabled("young-flag"):
        return 0
    return sum(cart) + 1
