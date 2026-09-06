"""Planted: bare call, client without timeout, client with timeout, call with timeout."""
import requests
import httpx

def a(url):
    return requests.get(url)


def b(url):
    s = requests.Session()
    return s.post(url, data={})


def c(url):
    cl = httpx.Client(timeout=5)
    return cl.get(url)


def d(url):
    return requests.post(url, timeout=(3, 10))
