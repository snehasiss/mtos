# ADR-006: MQTT for accessory messaging

- Status: Superseded by ADR-007
- Date: 2026-09-06
- Origin: Consolidates the accepted layout-automation ADR-003

## Context

Accessory nodes need lightweight local messaging on an SBC. Locomotive and
track-power control remain on the direct EX-CSB1 serial path and do not depend
on Wi-Fi or MQTT. The original evaluation estimated Mosquitto at under 10 MB
of memory and a Node-RED deployment at over 100 MB; these are planning
estimates to verify on the target Cubietruck, not guaranteed limits.

## Decision

Run Eclipse Mosquitto locally on the SBC and use the Paho MQTT client in the
Python application. Node-RED is not part of the core control loop or required
runtime; it may be used separately as an optional diagnostic tool.

Accessory commands use QoS 1. Consumers must therefore be idempotent because
delivery is at least once and duplicates are valid. Mosquitto persistence is
enabled to improve delivery continuity across broker restarts.

Retained messages may represent the latest **desired** state, but they are not
proof of physical state and are not the authoritative asset or operational
record. A node must publish acknowledgement and reported state after applying a
command. MTOS persists durable configuration and relevant state in SQLite.

The early prototypes used these topic shapes and integer payloads:

```text
layout/{node_id}/turnout/{channel}/set   0 = straight/main, 1 = diverging
layout/{node_id}/signal/{channel}/set    0 = dark/stop,     1 = lit/clear
```

Here, `node_id` identifies the ESP32 and `channel` is a physical PCA9685
channel. These are retained as historical/reference conventions, not frozen as
the public MTOS contract. The final contract must use stable logical accessory
IDs and configuration mappings rather than expose physical channels to domain
callers. It must define command ID, configuration revision, issued/expiry time,
desired state, acknowledgement, reported state, errors, and node availability.

## Startup and failure policy

- Nodes publish availability using MQTT Last Will and Testament.
- A stale retained command must not cause an unsafe or surprising movement.
- Startup behavior is explicit per accessory: restore desired state, reconcile
  without movement, move to a configured safe state, or require operator action.
- Interlocking and route validation occur before commands are published.
- Broker authentication, per-node credentials, topic ACLs, and protected
  administration are required even on the local layout network.
- Wi-Fi is asynchronous and may disconnect; the system makes no absolute
  latency guarantee. Loss of MQTT must not affect direct locomotive control.

The broker and client-library choices are accepted. The versioned topic and
payload contract must be decided and tested before implementation compatibility
is claimed.
