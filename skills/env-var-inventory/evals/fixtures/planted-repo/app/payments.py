"""Planted fixture: a secret with a literal fallback."""
import os
from os import environ

API_BASE = environ.get("API_BASE")


def client():
    return os.environ.get("STRIPE_API_KEY", "sk_test_123")  # planted: secret with default
