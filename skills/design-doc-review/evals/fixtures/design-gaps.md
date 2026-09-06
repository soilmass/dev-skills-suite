# Checkout retries

## Background

Payment gateway calls fail transiently about 2% of the time and we
currently surface every failure to the customer.

## Goals

- Retry transient gateway failures without duplicating charges.
- Keep p99 checkout latency under 2 s.

## Proposed design

Wrap the gateway client in an idempotent retry with an idempotency
key derived from the order id. Budget: 3 attempts, TBD backoff.

```python
# TODO: this placeholder is inside a code block and must not be reported
def retry(): ...
```

## Alternatives considered

- Do nothing and keep surfacing failures.

## Risks

## Open questions

- Does the gateway honour idempotency keys across regions? @priya
- What is the backoff ceiling? [FILL: after load test]
