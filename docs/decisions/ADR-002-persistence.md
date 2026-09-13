# ADR-002: Embedded transactional persistence

- **Status:** Accepted
- **Date:** 2026-09-06

## Context

Independent JSON files are transparent and portable, but they cannot reliably
enforce references, uniqueness, coordinated updates, or concurrent access.
MTOS needs atomic changes spanning asset lifecycle, control configuration, and
transaction records while remaining suitable for a small SBC.

## Decision

Use one embedded SQLite database as the authoritative live store for an MTOS
installation.

The roster database is `data/db/mtos.sqlite3`; photos are in `data/media`.
Both are excluded from Git. `MTOS_DATA_DIR` configures another live data root.
Manual `tools/mtos_backup --remote PATH --backup` snapshots the database and media together;
there is no installed backup schedule. See `docs/operations/roster.md`.

- Important identities, relationships, states, and query fields use relational
  columns with database constraints.
- JSON columns are reserved for genuinely variable attributes and protocol
  payloads; SQLite is not used merely as an unstructured JSON bucket.
- Foreign-key enforcement is enabled on every connection.
- Schema changes are versioned migrations committed to the repository.
- JSON remains an import, export, fixture, API, and human-readable snapshot
  format, but is not the live transactional authority.
- The asset-management application boundary owns persistent asset writes.
  Hardware adapters do not independently edit the database.

## Transaction boundary

SQLite can make multiple database changes atomic. It cannot make a physical
decoder or command station participate in a database transaction. Operations
that cross software and hardware boundaries therefore use durable workflows
with explicit intermediate and recoverable failure states.

For example, a decoder-address change conceptually performs:

```text
validate and reserve address
        -> program physical decoder
        -> read and verify decoder
        -> commit control configuration
        -> publish new operating projection
```

The workflow is not complete until physical verification and persistent
configuration agree.

## Alternatives considered

### Independent JSON files

Rejected as the future authoritative store because cross-record invariants and
atomic multi-record updates would have to be rebuilt in application code.

### Client/server relational database

Deferred because MTOS does not initially require a database daemon, remote
administration, or high write concurrency.

### Document database server

Deferred because it adds an operational service without removing the need for
explicit relationships, uniqueness, and transaction design.
