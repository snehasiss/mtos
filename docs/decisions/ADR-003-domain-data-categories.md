# ADR-003: Domain data categories

- **Status:** Superseded by ADR-008
- **Date:** 2026-09-06

## Context

The predecessor model composed rolling stock from `Identity`, `Prototype`,
`Model`, and `Control`, but mixed stable description, acquisition progression,
asset condition, installed configuration, and operational eligibility. It also
placed mutable current state beside master data in some design proposals.

MTOS must separate those meanings without weakening invariants. In particular,
an asset that is intended, shipped, under repair, retired, or inconsistently
configured must not become available for operation.

## Proposed decision

MTOS distinguishes five data categories. They may live in one transactional
database while remaining separate domain concepts.

### 1. Master data

Stable identity and physical classification: the asset ID, kind, manufacturer,
product identity, scale, prototype description, and type-specific physical
characteristics.

### 2. Lifecycle data

Current authoritative progression and condition, separated into dimensions
rather than compressed into one status: acquisition, possession, service
condition, and commissioning or retirement.

### 3. Configuration data

Mutable technical configuration applied to an asset: installed decoder,
address, address mode, functions, capabilities, calibration, and applicable
control protocol.

### 4. Operational state

Current volatile or observed railroad state: speed, direction, active
functions, occupancy, turnout position, signal aspect, track power, and control
session. Operational state is not asset master data.

### 5. Transactions and events

Durable facts about changes and coordinated workflows: acquisition, receipt,
maintenance, decoder installation, address programming, commissioning,
movement, and retirement.

Every applicable record links through the immutable global `asset_id`.

## Invariant

Operational availability is a derived, authoritative decision, not an
independent boolean. It is computed from a consistent view of lifecycle,
condition, configuration, relationships, and relevant layout constraints.

Separating these categories does not permit them to drift independently. A
domain operation validates and commits all database changes required to
preserve the invariant within one transaction. Cross-hardware operations use a
durable workflow as described in ADR-002.

## Open questions

- Exact lifecycle dimensions and permitted transitions
- Whether prototype/catalog records are shared master data distinct from owned
  physical assets
- Versioning and effective dating of control configuration
- Which operational state is persisted across restart
- Deployment and eligibility projection consumed by control adapters
- Ownership and lifecycle of asset relationships such as pilot, booster,
  consist, and permanent coupling
