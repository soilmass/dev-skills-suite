# ADR-0001: PostgreSQL (managed)

- status: accepted
- date: 2024-03-11

## Context and Problem Statement

The service needs a primary datastore. Reads dominate, the schema is relational, and the team has operated PostgreSQL before but not MongoDB.

## Decision Drivers

- relational schema with foreign keys across five core tables
- team operational experience

## Considered Options

- PostgreSQL (managed)
- MongoDB Atlas
- SQLite embedded

## Decision Outcome

Chosen option: "PostgreSQL (managed)", because it matches the relational schema and the team can operate it today.

### Consequences

Good:

- referential integrity enforced by the database

Bad:

- vertical scaling limits on the managed tier

## Confirmation

The schema migration tooling targets PostgreSQL only.
