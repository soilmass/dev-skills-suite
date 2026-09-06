"""Planted fixture: a definition referenced only through a string key.

Static name counting cannot see REGISTRY["plugin_hook"]() in main.py as
a reference to plugin_hook, so the scanner treats any name that appears
inside a string literal as possibly-used and must NOT report it.
"""


def plugin_hook():
    return "hooked"


REGISTRY = {"plugin_hook": plugin_hook}
