"""Planted fixture: one test per smell beside clean tests that must stay silent."""
import time

import pytest


@pytest.fixture
def order():
    return {"id": 1, "qty": 2}


def helper_without_assert(order):
    # not a test: draws nothing even though it asserts nothing
    return order["qty"]


def test_total_is_computed(order):
    assert order["qty"] * 10 == 20


def test_raises_on_missing():
    with pytest.raises(KeyError):
        {}["missing"]


class TestCart:
    def test_add(self):
        self.assertEqual(1, 1)

    def test_prints_only(self):  # planted: no assertion
        print("looks fine")


def test_waits_for_worker(order):  # planted: sleep
    time.sleep(0.5)
    assert order["id"] == 1


def test_ignores_errors(order):  # planted: swallowed exception
    try:
        helper_without_assert(order)
    except Exception:
        pass
    assert True


def test_each_case(order):  # planted: conditional logic
    for qty in (1, 2, 3):
        if qty > 1:
            assert qty * 10 > 10
