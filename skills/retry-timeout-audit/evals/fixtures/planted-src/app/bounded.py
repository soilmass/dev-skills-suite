"""Planted: bounded retry with constant sleep and a narrow handler."""
import time
import requests


def fetch(url):
    for attempt in range(3):
        try:
            return requests.get(url, timeout=5)
        except requests.ConnectionError:
            time.sleep(2)
    raise RuntimeError("gave up")
