"""Planted fixture: use through a from-import alias."""
from requests import Session as S

def upload():
    s = S()
    s.mount("https://", None)
    return s
