"""Safe: timeout set."""
import requests


def ok(url):
    return requests.get(url, timeout=3)
