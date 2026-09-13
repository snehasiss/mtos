# asset_control: requirements review and implementation plan

Date: 2026-09-13. Status: proposed, not an accepted ADR or coding authorization.
Scope: first DCC-EX control increment on port 5302, using Python/Flask and an
iPhone-first interface. No hardware commands were sent during this review.

## Conclusion

The predecessor provides a useful working baseline, but MTOS does not yet have
a complete control contract. Device discovery is present there; verified device
readiness, output awareness and programming recovery are incomplete. Reuse the
working protocol pieces with tests, not the entire service unchanged.

## Evidence from the predecessor

Source root: `/Users/snehasis/project/union-pacific-layout/src/csb1`.

| Area | Existing behavior | Gap for MTOS |
| --- | --- | --- |
| serial/discovery.py | Lists path, description, manufacturer, VID/PID, serial number; refuses ambiguous auto selection | Auto heuristic uses path names, not verified CSB1 identity; misses typical ttyUSB names |
| serial/controller.py | Reader/framer thread, write/request locks, command queue, blocking CV requests | Opening a port immediately reports connected; no readiness handshake; reconnect options unused; queue survives disconnect |
| serial/parser.py | Identity, global p0/p1, locomotive and selected r-format CV frames | No A/B modes, scoped power, current/trip state; function reporting only F0–F15 despite sending through F68 |
| api/routes.py | Connect/disconnect, power, throttle, functions, stop, service CV read/write | Track parameter not allowlisted; no output-role checks, mode switching or programming-on-main API |
| state.py | Thread-safe in-memory snapshot | Global power defaults off even before hardware observation; no unknown/stale output states |
| CV requests | Read uses fixed callback 1; write matches CV number | Delayed same-CV responses can be confused with later requests; no hardware readback workflow |
| operating responses | API returns accepted after queuing | Desired values immediately enter the same snapshot as reported values |
| frontend | Operation/programming tabs, throttle, functions, CV entry | Selecting Programming only changes the screen, not the command-station output mode |
| roster.py | Active DCC locomotives from legacy roster | Needs MTOS eligibility, asset IDs and revision-aware configuration |
| tests | 32 passed in this review | CV API responses mocked; no real programming proof or serial recovery integration coverage |

The commissioning log records firmware 5.6.3, A=MAIN, B=PROG and only A wired
to an isolated track. The owner confirms ordinary operation works and CV testing
is incomplete. Treat the recorded firmware as historical until queried again.

Specific risks to fix during porting:

- Commands pending when a connection fails must not execute after reconnection.
- The reader's serial-error path must wake pending requests and close/reset the
  connection rather than leave them waiting for the full timeout.
- Checking request_lock.locked() before enqueueing is not an atomic scheduling
  boundary. One transport owner must serialize programming and normal commands.
- Emergency actions must cancel pending movement, not merely jump ahead of it.
- A lost command-station connection means unknown hardware state, not power off.
- HTTP CSRF/origin protections must follow MTOS; do not copy wildcard-origin and
  development-secret defaults from the predecessor.

## Physical outputs, locations and programming modes

Do not conflate these three identities:

- Physical output: A or B on the EX-CSB1.
- Configured electrical role: MAIN or PROG.
- Layout location: test_main_1 or test_prog_1 in the inventory.

DCC-EX documents configurable MAIN/PROG output roles and permits only one PROG
output. Changing another output to PROG displaces the previous one. Its manual
confirms that A/B are configurable, not immutable MAIN/PROG terminals.
[TrackManager](https://dcc-ex.com/trackmanager/index.html),
[EX-CSB1 manual](https://dcc-ex.com/ex-commandstation/rtr-manual.html).

### Recommended two-track bench arrangement (proposal)

| Physical wiring | Normal purpose | MTOS workflow |
| --- | --- | --- |
| A -> test_main_1 | Ordinary running test | Keep A in MAIN |
| B -> test_prog_1 | Single-locomotive programming/run bench | Switch B between PROG and MAIN under a guarded workflow |

This makes the second track useful for both programming and checking behavior
without lifting the locomotive between every edit. test_prog_1 remains its
physical location even while B is in MAIN mode. Moving to the larger running
track is optional, not necessary for every programming cycle.

For the existing single isolated track, software role switching on A is a
possible interim workflow, subject to confirming the installed firmware and
safe configuration of the other output. Do not switch a whole operating layout
into PROG. The two-track bench arrangement is the preferred initial target.

MTOS's proposed transition procedure:

1. Operator selects the bench location and confirms exactly one locomotive on
   the programming section, electrically isolated on both rails.
2. Acquire one programming lock; reject other programming/movement commands.
3. Stop the selected locomotive, cancel its queued motion, and turn the selected
   output off. Require current hardware feedback before changing its role.
4. Set the requested role, query configuration, and verify it; refuse an
   unexpected existing PROG assignment rather than silently displacing it.
5. In PROG, enable CV actions only after checks. In MAIN, require explicit run
   power and start at speed zero. Never restore the old speed automatically.
6. On failure, block further programming/run actions and show unknown/error;
   request power off where communication remains available, then reconcile.

The tracks must not electrically bridge during programming. A separate test
section is simplest. Do not connect A and B terminals together. If a future
drive-on programming siding is wanted, its insulated boundaries, train length
and safe crossing behavior need a separate wiring review.

JOIN is a separate DCC-EX capability that feeds MAIN packets to the PROG track;
it is not necessary for this initial isolated-bench workflow. Service programming
and addressed programming-on-main are different commands. The documented PoM
write has no response, so it must not be displayed as verified; normal service
CV reads must not be presented as MAIN reads.
[Native command reference](https://dcc-ex.com/reference/software/command-summary-consolidated.html).

## Minimal device awareness

Keep this small: one configured command-station connection, its detected identity
and its outputs. Do not create a general-purpose device registry framework.

- Persist configured adapter, selected USB identity/path and location-to-output
  mapping. Use stable Linux device identity where available; allow explicit
  selection on the iMac. Never claim a USB bridge VID/PID proves it is a CSB1.
- Runtime connection states: disconnected, connecting, ready, error; readiness
  requires a valid DCC-EX exchange, identity/version and output discovery.
- Separate expected configuration from reported configuration. Show last_seen
  and stale/unknown state; expose only capabilities actually verified for the
  installed firmware. Do not open every serial port looking for a device.
- Each output reports output letter, location, observed mode, observed power and
  current/fault information when supported. Unsupported readings remain unknown.
- Exactly one process owns the serial port. Stop legacy dcc_service and release
  browser serial clients before asset_control connects. Other native throttles
  can still compete through the CSB1; the initial bench test needs one operator.
- No automatic power/throttle restoration. Reconnection may rediscover hardware,
  but commands from the old connection session must be discarded.
- Device presence does not establish which locomotive is on a track. Without
  occupancy/identification sensors, the operator confirms placement; a decoder
  address read alone is not guaranteed unique roster identity.

Command-station inventory classification/ID is not settled by ADR-008; do not
invent a new asset family or overload Nxxx accessory nodes silently. Initially
represent the connection as service configuration, pending that inventory choice.

## Asset boundary and programming integrity

Use MTOS asset_id as the application reference; resolve the current DCC address
from the roster rather than maintaining a second locomotive master list.

Proposed ordinary-run eligibility: received + active + DCC configuration, valid
address and satisfied dependencies. Parked-to-active activation should be
explicit, not silently bypassed. Workshop programming needs a separate
permission rule: received + operator-confirmed isolated bench placement, allowing
maintenance assets without pretending they are active operating locomotives.
The exact parked/maintenance workflow needs owner confirmation.

SQLite transactions cannot be atomic with physical decoder writes. For address
changes use a durable operation record: pending -> hardware verified -> roster
committed, or failed/uncertain. Hold the relevant operating lock, retain old/new
addresses and roster revision, and block normal use while uncertain. A crash
after hardware success but before the DB commit requires reconciliation, not
blind retry or a false rollback claim. Finalize this contract before implementing
address-changing CVs or a dedicated address action. Generic CV writes that affect
addressing must not bypass it.

Separate queued/sent, device-reported, verified and uncertain outcomes. CV writes
should be followed by readback for the initial service-mode workflow. No automatic
write retries after timeout. Persist useful programming outcomes, not an unbounded
serial transcript; keep bounded diagnostic logs for failed bench tests.

## Incremental implementation plan

1. **Freeze a small control ADR:** approve bench arrangement, device readiness,
   per-output state, eligibility and programming failure semantics. Reconcile
   inventory/control ownership; leave MQTT accessories outside this increment.
2. **Transport and device status:** port framing/commands/parser with a fake serial
   transport; add handshake, output parsing, exclusive ownership, clean shutdown,
   queue cancellation and reconnection resynchronization. Wire tools/asset_control
   to the real service at 0.0.0.0:5302. Reuse Flask/phone-first conventions, not
   the old React build as an obligatory new runtime stack.
3. **Operating parity:** eligible roster, selected locomotive, speed/direction,
   functions, locomotive stop, global emergency stop and independent A/B power.
   UI distinguishes motion stop from power off and unconfirmed from observed state.
4. **Bench programming:** guarded PROG/MAIN transition, read-only decoder/CV checks,
   then one explicit write plus readback. Handle no ACK, delayed responses,
   disconnected hardware and user cancellation. Add address-change orchestration
   only after its persistence contract is agreed and ordinary CV tests are sound.
5. **Commission and checkpoint:** run the automated suite, then supervised CSB1
   tests. Record actual firmware, decoder and wiring; document results and update
   mtos-context.md. PoM and JOIN remain explicit later choices, not implicit scope.

Suggested module home: src/mtos/control/ with a small DCC-EX adapter, runtime state
and application routes; reuse service management, roster validation and database
migration conventions. Final module/API schema belongs in the approved ADR.
No generic plugin framework, extra broker or second roster database is proposed.

## Acceptance tests

Automated, without hardware:

- USB selection: none/one/multiple candidates, changed paths, wrong-device reply,
  busy port, open-but-silent device and readiness timeout.
- Framing: partial/combined/noisy input; identity, modes, scoped/global power,
  applicable CV response forms, malformed and negative responses.
- Command scheduling: disconnect with queued throttle, emergency preemption,
  concurrent HTTP clients, programming exclusivity and late responses after timeout.
- Track modes: unknown/mismatched state, existing PROG elsewhere, mode-change
  failure, no implicit power-on, no movement replay.
- Roster rules: shipped/retired denied, maintenance bench handling, stale revisions,
  dependency failures, address collision and uncertain address-write recovery.
- Security/API/UI: validated enums and scalar types, CSRF, no arbitrary serial
  injection, phone controls disabled when not ready, explicit power/mode status.

Supervised hardware, with owner approval at each write/movement stage:

1. No-load identity/output discovery; independently verify A/B power indications.
2. One known decoder on isolated B: repeated read-only identification and CV reads.
3. Write one agreed reversible CV, read back and restore its original value.
4. Switch the same bench track to run mode, verify zero speed, test at low speed,
   stop, and return to programming without moving the locomotive or wires.
5. Disconnect/reconnect and service restart: no replay or unexpected energizing.
6. Only then test an address change, including interrupted-result reconciliation.

Do not deliberately short hardware as a software test. If overcurrent behavior is
to be commissioned, use manufacturer-approved procedures separately. Software
cannot guarantee power removal through a disconnected USB link; retain an
accessible physical power-off method.

## Remaining owner decisions

- Approve A as the run track and B as a switchable isolated programming/run bench.
- Confirm whether both proposed test tracks are physically separate (recommended
  for this first increment), rather than connected by a turnout.
- Agree maintenance/parked eligibility and the coordinated address-update workflow.
- Confirm current CSB1 firmware and choose the first test locomotive/CV before
  hardware commissioning. The prior firmware/decoder log is not a live observation.

Review verification: predecessor CSB1 suite **32 passed** on 2026-09-13 using
PYTHONDONTWRITEBYTECODE=1 and pytest cache disabled. No predecessor code, live
roster data, serial settings, track mode, power or decoder CV was changed.
