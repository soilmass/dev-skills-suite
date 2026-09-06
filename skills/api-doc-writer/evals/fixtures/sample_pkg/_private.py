"""A private module: excluded from the reference unless --include-private."""


def internal_only():
    """Must not appear in the public reference."""
    return True
