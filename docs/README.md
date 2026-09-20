# MTOS design documentation

MTOS uses Architecture Decision Records (ADRs) to distinguish settled decisions
from proposals still under discussion.

## Decisions

- [ADR-001: Product scope and system boundaries](decisions/ADR-001-product-scope.md)
- [ADR-002: Embedded transactional persistence; ownership amended by ADR-009](decisions/ADR-002-persistence.md)
- [ADR-003: Domain data categories; superseded by ADR-008](decisions/ADR-003-domain-data-categories.md)
- [ADR-004: Decentralized accessory-control nodes; superseded by ADR-007](decisions/ADR-004-decentralized-accessory-nodes.md)
- [ADR-005: Accessory power distribution; superseded by ADR-007](decisions/ADR-005-accessory-power-distribution.md)
- [ADR-006: MQTT for accessory messaging; superseded by ADR-007](decisions/ADR-006-mqtt-accessory-messaging.md)
- [ADR-007: Stationary assets, control network, and power management](decisions/ADR-007-stationary-assets-control-network-and-power.md)
- [ADR-008: Normalized asset-management and roster domain](decisions/ADR-008-asset-inventory-model.md)
- [ADR-009: Service decomposition and real-time control architecture](decisions/ADR-009-service-decomposition-and-control-architecture.md)
- [ADR-010: Asset lifecycle and decoder-address ownership](decisions/ADR-010-asset-lifecycle-and-decoder-address-ownership.md)
- [ADR-011: Cubietruck operating-system and Python environment](decisions/ADR-011-cubietruck-setup.md)
- [ADR-012: Deploying MTOS on Cubietruck A20](decisions/ADR-012-porting-mtos-on-cubietruck.md)

## Current architecture and operations

- [Real-time control-service architecture](architecture/control-service-architecture.md)
- [mtos_dcc module checkpoint](architecture/mtos-dcc-module.md)
- [mtos_core module checkpoint](architecture/mtos-core-module.md)
- [mtos_hmi module checkpoint](architecture/mtos-hmi-module.md)
- [mtos_mc scope and low-level design](architecture/mtos-mc-module.md)
- [Run, migrate and back up the roster](operations/roster.md)
- [Integrated service startup and shutdown](operations/service-startup.md)
- [Cubietruck installation context and commissioning evidence](operations/cubietruck-installation-context.md)
- [System context and bounded contexts](architecture/system-context.md)
- [Layout automation architecture](architecture/layout-automation.md)
- [Domain vocabulary](domain/vocabulary.md)

## Historical design baselines

These retain requirements and rationale but their monolithic `asset_control`,
shared-database or HTTP-polling topology is superseded by ADR-009.

- [Phase 1 CSB1 MAIN low-level design](architecture/asset-control-phase-1-low-level-design.md)
- [asset_control implementation contract — 2026-09-17 review](architecture/asset-control-implementation-contract.md)
- [asset_control pre-design](architecture/asset-control-pre-design.md)
- [asset_control device-interface plan](architecture/asset-control-device-interfaces.md)
- [EX-CSB1 predecessor review](architecture/asset-control-plan.md)

## Reviews

- [Layout automation ADR review](reviews/layout-automation-review.md)
- [Service architecture design review — 2026-09-18](mtos-review-design-2026-09-18.md)

An ADR marked **Proposed** is not an implementation commitment. It exists so
the model can be reviewed against real railroad operations before code and
migrations depend on it.
