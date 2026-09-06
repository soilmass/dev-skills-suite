"""A clean, one-way import: user depends on base, base does not depend
back, so there is no cycle."""
import base


def use_it():
    return base.base_thing()
