"""Planted fixture: uses the Session API that 3.0.0 breaks."""
import requests


def client():
    s = requests.Session()
    s.mount("https://", requests.adapters.HTTPAdapter())
    return s


def fetch(url):
    return requests.get(url, timeout=5)
