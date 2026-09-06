"""Planted fixture: comments that mention proper nouns which happen to
look like identifiers (CamelCase with no spaces) but are not code
references — must produce nothing. Found dogfooding this skill on the
family repository itself: comments mentioning GitHub, PyYAML, and
OpenAPI were misread as dangling references to undefined symbols."""


def build_request(payload):
    # GitHub's REST API wants JSON
    # PyYAML would emit the same shape reading the spec back
    # the OpenAPI spec is the source of truth for the field names
    return payload
