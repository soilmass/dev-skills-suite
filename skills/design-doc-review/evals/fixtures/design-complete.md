# Checkout retries

**Status:** draft · **Authors:** @priya, @marco · **Date:** 2026-09-05

## Context

Payment gateway calls fail transiently about 2% of the time.

## Goals

- Retry transient failures without duplicate charges.

## Non-goals

- Retrying declined cards.

## Proposed design

An idempotent retry wrapper keyed by order id, three attempts,
exponential backoff capped at 800 ms.

## Alternatives considered

- Client-side retry in the web app: duplicates charges when the
  first call succeeded but the response was lost.
- Queue and reconcile asynchronously: correct, but moves checkout
  off the request path and changes the customer experience.

## Risks and mitigations

- Gateway ignores the key in one region — mitigated by a
  reconciliation job that voids duplicates within five minutes.

## Rollout

Behind a flag, 1% of traffic for a day, then 100%; rollback is the
flag.

## Open questions

- Backoff ceiling after the load test (owner: @marco)
