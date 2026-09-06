# Changelog

## 3.0.0

- BREAKING: `Session.mount` removed; use the adapters mapping on the session instead.
- BREAKING: the `timeout` argument no longer accepts a tuple.
- Added: HTTP/2 by default.

## 2.32.0

- Deprecated: `requests.utils.get_encodings_from_content` will be removed in 3.0.
- Fixed: connection pool sizing.

## 2.31.0

- Fixed: a cookie jar regression.

## 2.30.0

- BREAKING: dropped Python 3.7.
