"""Planted fixture: a second importer using only post."""
from requests import post


def upload(url, data):
    return post(url, data=data, timeout=5)
