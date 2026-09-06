"""A team wrapper the default patterns do not know."""
import http_client


def f():
    return http_client.fetch("u")
