"""Helpers used by the client."""


def retry(fn, attempts: int = 3):
    """Call `fn` up to `attempts` times, re-raising only the final failure."""
    for i in range(attempts):
        try:
            return fn()
        except Exception:
            if i == attempts - 1:
                raise


def _backoff(i: int) -> float:
    return 2.0 ** i
