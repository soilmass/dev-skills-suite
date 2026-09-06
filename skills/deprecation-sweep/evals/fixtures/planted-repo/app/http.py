"""Planted fixture: one-hop use and a direct attribute use."""
import requests
import requests.utils


def client():
    s = requests.Session()
    s.mount("https://", requests.adapters.HTTPAdapter())
    return s


def sniff(body):
    return requests.utils.get_encodings_from_content(body)


def fetch(url):
    return requests.get(url, timeout=5)
