# MTOS design documentation

MTOS uses Architecture Decision Records (ADRs) to distinguish settled decisions
from proposals still under discussion.

## Decisions

- [ADR-001: Product scope and system boundaries](decisions/ADR-001-product-scope.md)
- [ADR-002: Embedded transactional persistence](decisions/ADR-002-persistence.md)
- [ADR-003: Domain data categories](decisions/ADR-003-domain-data-categories.md)
- [ADR-004: Decentralized accessory-control nodes](decisions/ADR-004-decentralized-accessory-nodes.md)
- [ADR-005: Accessory power distribution](decisions/ADR-005-accessory-power-distribution.md)
- [ADR-006: MQTT for accessory messaging](decisions/ADR-006-mqtt-accessory-messaging.md)
- [ADR-007: Stationary assets, control network, and power management](decisions/ADR-007-stationary-assets-control-network-and-power.md)
- [ADR-008: Normalized asset-management and roster domain](decisions/ADR-008-asset-inventory-model.md)

## Working architecture

- [System context and bounded contexts](architecture/system-context.md)
- [Layout automation architecture](architecture/layout-automation.md)
- [Domain vocabulary](domain/vocabulary.md)

## Reviews

- [Layout automation ADR review](reviews/layout-automation-review.md)

An ADR marked **Proposed** is not an implementation commitment. It exists so
the model can be reviewed against real railroad operations before code and
migrations depend on it.
