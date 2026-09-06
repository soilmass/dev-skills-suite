"""Planted fixture: three debt markers at known lines (SDS-S-095)."""


def load(path):
    # TODO: support gzip input
    with open(path) as f:
        return f.read()


def parse(text):
    # FIXME: silently drops the last record when the file has no trailing newline
    return [line.split(",") for line in text.splitlines()]


def total(rows):
    # HACK: assumes column 2 is always numeric
    return sum(int(r[2]) for r in rows)
