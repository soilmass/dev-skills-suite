"""Planted fixture: not a test file; its sleep must not be scanned."""
import time


def test_like_but_not_a_test():
    time.sleep(1)
