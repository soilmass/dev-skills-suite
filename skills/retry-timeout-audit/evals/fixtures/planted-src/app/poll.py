"""Planted: while True retry, constant sleep, broad except."""
import time
import requests


def poll(url):
    while True:
        try:
            return requests.get(url, timeout=5)
        except Exception:
            time.sleep(5)
            continue
