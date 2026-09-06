# ADR-001: Product scope and system boundaries

- **Status:** Accepted
- **Date:** 2026-09-06

## Context

The predecessor repository grew from a specific Union Pacific HO layout and
eventually combined asset-management software, a DCC-EX command-station service,
and optional conversational services. That experience demonstrated the need for
a clean, product-level boundary.

MTOS is intended to replace the normal need for Java-based desktop suites and
separate phone throttle applications. A user should be able to download MTOS,
configure supported hardware, and operate a layout from an ordinary browser.

## Decision

The product is named **MTOS — Model Train Operating System**.

MTOS is:

- a standalone model-rail asset-management and operating platform;
- lightweight enough for a modest single-board computer;
- accessed primarily through a browser on phones, tablets, and computers;
- independent of scale, prototype railroad, command station, and protocol;
- usable without JMRI, WiThrottle, or an equivalent runtime dependency;
- open source under Apache License 2.0.

The initial product contains two critical domains:

1. **Asset management**, which owns durable knowledge about model-rail assets.
2. **Railroad operation**, which owns live interaction with the layout and its
   control systems.

Search, chat, and language-model features are optional adapters and are never
part of the safety or integrity-critical path.

## Consequences

- The Union Pacific layout is migration input and a test case, not the MTOS
  domain boundary.
- Hardware-specific terminology must not leak into common asset identity.
- An installation may operate entirely on the local layout network.
- Loss of an optional AI or chat component cannot prevent asset management or
  railroad operation.

