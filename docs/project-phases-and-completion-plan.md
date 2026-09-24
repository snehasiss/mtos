# MTOS project phases and completion plan

Status: planning and audit checkpoint, 2026-09-24. This document records the
agreed phase boundary and the work needed to claim each phase complete. It is a
roadmap, not a claim that hardware has been commissioned. ADR-001, ADR-007,
ADR-008, ADR-009 and ADR-010 remain the governing domain and service decisions.

## Phase boundary

**Phase 1 is supervised operation and asset management.** It comprises the
Asset roster and administration/backup path; browser-led DCC MAIN locomotive
control; guarded address and individual-CV programming on an isolated PROG
track; and a supervised accessory pilot for turnouts, signals and a trackside
machine through MC, MQTT and ESP32. An operator remains present, selects the
asset and operation, checks physical conditions and can remove power. Phase 1
does not claim physical turnout position or signal illumination without feedback
sensors. The PROG-track low-speed test mode remains a separately commissioned
part of this phase; it is currently disabled.

**Phase 2 adds occupancy detection, routes, interlocking and automated
operation.** An Axon-class host with a lightweight local LLM is planned for
interpreting user input and proposing path plans or navigation intents. Hardware
selection and capacity are not yet finalized. The LLM is not a source of
occupancy truth and never issues raw DCC, MQTT, servo or signal commands. Core
must validate proposed intents against deterministic route, occupancy,
reservation and interlocking rules before any hardware adapter acts. Manual
supervised operation must remain available if the LLM or Axon is offline. This
preserves the safety and authority boundary in [ADR-009](decisions/ADR-009-service-decomposition-and-control-architecture.md).

Asset management is not a prerequisite for every physical experiment, but its
identity, configuration and lifecycle records must be correct before MTOS uses
an asset for normal operation. The Phase 1 outcome is a commissioned,
recoverable supervised system, not merely a successful fake-hardware test.

## Current evidence and limits

The five application services and Admin exist. Asset uses schema v6 with a
uniform `control` shape; passenger and freight use separate `P` and `F` IDs.
The DCC MAIN and address/single-CV software flows are integrated with Core and
HMI. The MC host path and ESP32 source exist against fake transports. The
normal Python suite passed 122 tests with one optional browser test skipped at
this checkpoint. An explicit attempt to run that browser test stopped before
execution because Playwright is absent from the reviewing environment. Neither
those tests nor the source review prove EX-CSB1, decoder, broker, ESP32,
electrical, latency or recovery behavior on the deployed host.

The [2026-09-18 code/documentation review](reviews/mtos-review-code_doc-2026-09-18.md)
identified control and recovery defects. Several still match current source,
including emergency admission/ordering, inability to persist stationary
configuration consumed by Core, lost MC execution identity, and firmware
active-command context handling. Treat the affected physical paths as
uncommissioned until these are fixed and retested. The review is historical
evidence, not a substitute for a fresh acceptance run after changes.

## Phase 1: owner hardware and setup work

1. **Maintain the deployed host and data path.** Keep the Cubietruck's MTOS
   checkout, secrets, service account and serial permissions working. Deploy a
   reviewed revision, run the suite on ARMv7, check five-service startup/status/
   shutdown, and prove both backup and restore with SQLite and media integrity.
   Record the running Git revision, kernel, Python version, memory, load and
   command latency. The iMac remote mirror is a current copy, not snapshot
   history.
2. **Construct the DCC pilot tracks.** Connect EX-CSB1 USB to the Cubietruck and
   use its specified independent supply. Wire output A to `test_main_1` (MAIN)
   and output B to `test_prog_1` (PROG), isolated on both rails with no common
   jumper. Provide an accessible physical means to remove track power. Record
   the station firmware and observed A/B mode and power reports. Choose one
   known-good test locomotive/decoder and record its starting address and CV
   evidence. Only one decoder may occupy PROG during service-mode programming.
   See the [CV programming plan](architecture/cv-programming-plan.md).
3. **Prepare one accessory pilot node before scaling out.** Set up the local
   broker, unique node identity, credentials and topic ACLs. Assemble a
   protected/fused 12 V accessory branch, local regulated 5 V, ESP32 and the
   relevant PCA9685 or 74HC595 output stages. Establish the actual
   asset-to-node/channel map and calibrated endpoints. Verify pin boot levels,
   polarity, current, driver and flyback requirements first without a load;
   then commission one unloaded servo, one turnout and test LEDs in stages.
   Keep DCC track power electrically separate from accessory power. The
   quantities in [ADR-007](decisions/ADR-007-stationary-assets-control-network-and-power.md)
   are provisional until the installed layout map and measurements are known.
4. **Connect machines only after measurement.** For the water tower, measure
   trigger voltage/current/polarity, required contact time, full cycle time and
   12 V consumption before selecting and wiring an isolated dry-contact relay.
   Turntables await mechanism, homing/feedback and action decisions. Record all
   measurements and physical outcomes as commissioning evidence.

## Phase 1: software and test work

The following order prevents physical commissioning from outrunning the control
and recovery contract.

1. **Close DCC control blockers.** Give emergency stop and shutdown a reliable
   stop barrier and admission path under load; invalidate previously admitted
   motion at final dispatch. Make backend motion depend on fresh, verified MAIN
   role/power evidence. Reject ambiguous active DCC addresses unless a future
   explicit consist policy allows them. Test queued commands, stale generations,
   serial silence, role changes, reconnect and saturation.
2. **Complete stationary configuration and fencing.** Persist the configuration
   revision, allowed actions, resources, node mapping, component wiring and
   calibration that Core and MC actually consume. Protect dependent resources
   and detect conflicting physical output assignments. Test using assets saved
   through the real API rather than test-only shapes.
3. **Make MC execution recoverable.** Persist the full execution identity before
   dispatch; reconcile lost replies and late/duplicate events by that identity;
   define expiry, timeout, cancellation, lease renewal/release and supervised
   uncertain-result resolution. Quarantine old queued work after authority
   changes. Preserve conservative resource gates until physical state is known.
4. **Repair and build the firmware.** Separate incoming and active execution
   context, preserve an unknown/in-progress turnout state through interruption,
   enforce producer epoch and bounded calibrated actions, and meet the target
   QoS 1 node-event contract or revise that contract deliberately. Build with
   PlatformIO and fault-test duplicates, resets and lost responses before a
   live broker or load is connected.
5. **Finish operator feedback and deployment behavior.** Keep command acceptance,
   completion and uncertainty distinct in Core/HMI; handle stale snapshots and
   adapter restarts; show per-asset readiness and disabled reasons. Bound browser
   tasks, output queues, journals and image-processing interference. Make
   launcher/process ownership, update and backup/restore behavior dependable
   under partial failure. Align RPC deadlines with actual hardware operations.
6. **Run staged acceptance tests.** Rebuild/typecheck the React UI, run actual
   browser tests on phone-sized and desktop viewports, run fake serial/MQTT
   fault injection and service restart tests, then measure Cubietruck memory,
   latency and emergency response under representative load. Commission the
   EX-CSB1 read-only first, then one reversible CV write, then one supervised
   address change. Commission JOIN/DriveAway and the bounded PROG-track run only
   after its return-to-PROG behavior is observed and recoverable. Commission one
   accessory node/output before adding further nodes.

**Phase 1 exit criteria:** the Asset/backup path is restorable; supervised DCC
MAIN and the agreed programming operations have physical readback evidence;
emergency stop and failure recovery have measured outcomes; at least one
turnout and representative signal/machine pilot have correlated MC/node
evidence; operators see uncertainty rather than false completion; and the
installed hardware configuration and runbook match the tested revision.

## Phase 2: design and implementation work

Phase 2 begins after Phase 1 can operate independently. The owner will select
and install occupancy sensors and their electrical interfaces, confirm block
boundaries and the layout topology, and provide an Axon-class host/network and
power arrangement suitable for the measured LLM workload. Sensor placement,
failure behavior and a physical route map must be reviewed before automation.

Software work then adds timestamped occupancy acquisition with explicit
unknown/stale states; a versioned block/turnout topology; deterministic route
planning, reservation and interlocking; signal aspects derived from verified
routes; bounded train/navigation control with manual override; and audit/replay
of decisions. The lightweight LLM can parse user requests and propose a route
or journey, but Core checks identity, current occupancy, conflicting routes,
turnout and signal readiness, speed limits and authority before execution.
Sensor loss, stale data, model failure and network partitions must fail closed
for automated movement. Scenario simulation and physical low-speed trials must
precede any unattended run.

**Phase 2 exit criteria:** every automated action is traceable from user intent
through deterministic Core validation to observed sensor/hardware evidence;
conflicts and unknown occupancy block movement; emergency and manual operation
remain independent of the LLM; and the installed layout passes fault-injection
and supervised end-to-end trials.

## Delivery and commissioning sequence

```mermaid
sequenceDiagram
    autonumber
    actor Owner as Owner/operator
    participant Dev as Coding and test work
    participant Host as Cubietruck MTOS
    participant DCC as EX-CSB1
    participant Decoder as Test decoder
    participant Node as Broker and ESP32 node
    participant Axon as Phase 2 Axon and LLM

    rect rgb(232, 242, 248)
        Note over Owner,Node: Phase 1 - supervised Asset, DCC and accessory pilot
        Owner->>Dev: Confirm installed hardware, track map and test asset
        Dev->>Dev: Fix control, recovery and firmware blockers
        Dev->>Dev: Run Python, browser, frontend and firmware tests
        Dev->>Host: Deploy reviewed revision and verify backup/restore
        Owner->>DCC: Wire isolated A MAIN and B PROG; provide power cutoff
        Host->>DCC: Connect; query identity, roles and power
        DCC-->>Host: Verified physical reports
        Owner->>Decoder: Place one known decoder on PROG
        Host->>DCC: Read address and selected CVs
        DCC-->>Host: Correlated readback evidence
        Owner->>Host: Supervise reversible CV and address trials
        Host->>DCC: Write, read back and conditionally update Asset
        Owner->>Node: Assemble, map and measure one protected node
        Host->>Node: Fenced MQTT handshake and one output command
        Node-->>Host: Correlated accepted/terminal evidence
        Owner->>Host: Verify physical outcome and recovery
    end

    rect rgb(238, 245, 230)
        Note over Owner,Axon: Phase 2 - occupancy, routes, interlocking and automation
        Owner->>Dev: Confirm blocks, sensors, topology and Axon arrangement
        Dev->>Host: Add sensor ingestion and deterministic route/interlocking logic
        Owner->>Axon: Request a route or journey in natural language
        Axon->>Host: Submit proposed intent and path, never raw outputs
        Host->>Host: Validate occupancy, conflicts, authority and readiness
        alt Safe and verified
            Host->>DCC: Issue bounded train command
            Host->>Node: Issue fenced turnout/signal command
            DCC-->>Host: Device evidence
            Node-->>Host: Accessory evidence
            Host-->>Owner: Report progress and exceptions
        else Unknown or conflicting
            Host-->>Owner: Reject or pause; request operator action
        end
    end
```

## Documentation maintenance

Before declaring either phase complete, reconcile the current README, module
checkpoints, startup guide, CV plan and Admin ADR with the implementation. At
this checkpoint they disagree about whether general CV software and the
Programming UI exist, whether Admin accepts arbitrary refs, and whether
startup proves the railroad unpowered. Repair broken relative links in the
documentation index and historical reviews. Preserve dated design history,
but label superseded behavior so an operator cannot mistake it for current
instructions.
