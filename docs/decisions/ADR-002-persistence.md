# ADR-002: Embedded transactional persistence

- **Status:** Accepted; persistence ownership amended by ADR-009
- **Date:** 2026-09-06

## Context

Independent JSON files are transparent and portable, but they cannot reliably
enforce references, uniqueness, coordinated updates, or concurrent access.
MTOS needs atomic changes spanning asset lifecycle, control configuration, and
transaction records while remaining suitable for a small SBC.

## Decision

Use embedded SQLite as the authoritative live persistence technology for an
MTOS installation. ADR-009 subsequently split runtime ownership by service, so
this no longer means one shared database file or cross-service SQL access.

Asset owns `data/db/asset.sqlite3`, Core owns `data/db/core.sqlite3`, and MC owns
bounded adapter evidence in `data/db/mc.sqlite3`. DCC and HMI have no Version 1
database. Photos are in `data/media`.
Both are excluded from Git. `MTOS_DATA_DIR` configures another live data root.
ADR-013 makes the complete `data/` tree one continuity unit and mirrors it to a
remote host with rsync over key-authenticated SSH; there is no installed backup
schedule. See `docs/operations/admin.md`.

- Important identities, relationships, states, and query fields use relational
  columns with database constraints.
- JSON columns are reserved for genuinely variable attributes and protocol
  payloads; SQLite is not used merely as an unstructured JSON bucket.
- Foreign-key enforcement is enabled on every connection.
- Schema changes are versioned migrations committed to the repository.
- JSON remains an import, export, fixture, API, and human-readable snapshot
  format, but is not the live transactional authority.
- Each state-owning service writes only its own database. Asset alone writes
  asset master/lifecycle/configuration data; Core alone writes canonical
  operational transactions; MC writes only subordinate execution evidence.
  Services communicate through versioned contracts, never cross-database SQL.

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
