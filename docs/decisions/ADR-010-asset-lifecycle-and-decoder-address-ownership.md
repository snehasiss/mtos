# ADR-010: Asset lifecycle and decoder-address ownership

- **Status:** Accepted
- **Date:** 2026-09-20
- **Amends:** ADR-008 and ADR-009

## Context

Inventory facts and physical decoder state cross three service boundaries. An
asset's lifecycle status is master data, while changing a DCC decoder address is
a physical programming operation followed by a master-data update. A stale Core
lease previously prevented Asset from saving lifecycle changes. Conversely, an
unqualified roster address edit can make the recorded address disagree with the
decoder.

SQLite cannot atomically commit a CV write performed by EX-CSB1. MTOS therefore
must state which service owns each fact and what happens between hardware success
and database success.

## Decision

### Lifecycle status

`mtos_asset` is the sole authority for `lifecycle.status` and the other asset
master data in `asset.sqlite3`. A Core reservation or Asset lease is information
about an operational consumer; it does not veto an Asset edit.

When an edit changes the operating view—family, type, control configuration,
relations, possession, status or location—Asset increments the asset revision
and retires affected leases/projections. Core must read the new revision and
revalidate before another ordinary command. Moving an active asset out of
`active` is allowed, but the UI warns when operational holds exist because a
database edit cannot stop already moving hardware.

### Decoder address

`control.decoder.address` remains Asset-owned master data. There are two explicitly
different write paths:

1. **Coordinated programming (normal path).** Core validates a received,
   maintenance-state, DCC-equipped self-propelled asset (`loco` or `mow`), holds
   its lease and records the operation. DCC exclusively owns EX-CSB1 serial I/O,
   programs the decoder on a verified PROG output with MAIN power off, and reads
   the affected CVs back. Only a confirmed readback allows Core to conditionally
   update Asset using the expected revision.
2. **Inventory-only override.** `mtos_asset` may directly edit
   `control.decoder.address`, but the UI must warn that this does not program or verify
   the decoder. This path exists for imports, corrections and externally
   programmed decoders. It never claims physical synchronization.

Version 1 supports addresses 1–10239. Programming commands are not automatically
retried after timeout. The original implementation manually wrote CV1/CV17/CV18/
CV29; the 2026-09-21 CV-programming review found that current DCC-EX guidance
requires its dedicated address command so consist and all required addressing CVs
are handled together. The manual sequence has now been replaced in software, but
the dedicated command remains physically uncommissioned. The design is recorded in
[the CV programming plan](../architecture/cv-programming-plan.md); this correction
does not change Asset/Core/DCC ownership or uncertain-result semantics.

### Failure outcomes

| Hardware result | Asset update | Canonical result |
|---|---|---|
| not verified | not attempted | `uncertain` |
| verified | succeeds at expected revision | `completed / confirmed` |
| verified | fails or revision changed | `uncertain`; retain old/new addresses and hardware evidence |

An uncertain address workflow requires supervised reconciliation. MTOS must not
blindly retry because the decoder may already use the new address.

## Service ownership

- `mtos_asset`: lifecycle and `control.decoder.address` persistence, revision checks,
  direct-edit warning and operating-view invalidation.
- `mtos_core`: eligibility policy, lease, durable workflow, old/new address and
  outcome, and conditional Asset update.
- `mtos_dcc`: exclusive serial programming, PROG/MAIN safety checks and CV
  readback; no Asset database access.
- `mtos_hmi`: operator-facing Programming workflow; no authoritative
  persistence.

## Implementation checkpoint

The service APIs, dedicated DCC-EX address command, CV encoding/parsing, guarded
address-programming workflow, readback, conditional Asset update, automated fake
transport tests and HMI Programming tab are implemented. Supervised physical
EX-CSB1/decoder commissioning remains pending. Until it is complete, the controls
must not be used to program a real decoder and are not a claim of hardware success.
