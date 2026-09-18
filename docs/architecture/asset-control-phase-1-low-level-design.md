# Phase 1: CSB1 MAIN low-level design

Status: implemented baseline under owner review, 2026-09-17. Physical CSB1
commissioning remains supervised and pending.
Companion: [implementation contract](asset-control-implementation-contract.md).
UI: [reviewed mockup](../mockups/asset-control-main.html).

> This is the historical monolithic Phase 1 baseline. ADR-009 supersedes its
> service topology, shared persistence, HTTP-command and polling runtime. Its
> DCC-EX encoders, parser behavior, UI requirements and fake-transport scenarios
> are migration inputs for `mtos_dcc`, `mtos_core` and `mtos_hmi`.

## Boundaries

Phase 1 delivers MAIN locomotive control, Flask API and iPhone UI on
0.0.0.0:5302. Phase 2 adds PROG CV programming to this same interface; Phase 3
adds MQTT/ESP32 accessories. No MQTT dependency or accessory tables in Phase 1.
Programming navigation is visible but disabled. No CV, JOIN, output-mode writes,
raw serial console or automatic block-location tracking.

## File structure and responsibilities

```text
src/mtos/
  control/
    __init__.py
    models.py          # typed commands, results, snapshots, errors
    config.py          # validated local service configuration
    repository.py      # reservations, command journal, roster projection
    service.py         # eligibility, orchestration, emergency generation
    runtime.py         # single device owner, bounded scheduling, lifecycle
    api.py             # Flask blueprint, request validation and responses
    dcc/
      __init__.py
      discovery.py     # USB metadata and explicit/unique selection
      protocol.py      # framing, encoders, typed parsers
      transport.py     # serial interface and pyserial implementation
  control_app.py       # Flask factory; no hardware side effects on import
  control_ui/          # committed Vite production bundle served by Flask
  migrations/004_control.sql
frontend/asset_control/
  src/App.tsx          # React control state and component composition
  src/api.ts           # typed Flask API client and CSRF handling
  src/types.ts         # API snapshot, roster and device types
  src/styles.css       # iPhone-first control presentation
  package.json
  vite.config.ts       # emits into src/mtos/control_ui
tools/
  asset_control        # existing launcher, now enabled
  build_asset_control_ui
  service.py           # select service and propagate its identity
  serve.py             # select factory, own lifetime locks and cleanup
tests/
  control/fakes.py
  control/test_protocol.py
  control/test_discovery.py
  control/test_runtime.py
  control/test_repository.py
  control/test_service.py
  control/test_api.py
  control/test_ui.py
```

Modify existing roster save/migration paths for reservation checks and schema v4.
Reuse restore locks, service health, data-root resolution and CSRF conventions.
Add `pyserial>=3.5,<4` to both dependency declarations when implementing. Python
3.11+, SQLite, Flask and Waitress remain the deployment stack; venv is optional.

## Configuration

Optional local `data/control.json`, outside Git, has one command-station connection.
Defaults are supplied in code and documented; malformed configuration fails startup.

| Field | Type/default | Meaning |
|---|---|---|
| serial_port | string/null | Explicit device or unique candidate selection on Connect |
| serial_number | string/null | Optional stable USB selection constraint |
| baud_rate | integer, 115200 | Serial baud rate |
| read_timeout_s | float, 0.05 | Bounded reader wake-up |
| write_timeout_s | float, 0.5 | Serial write bound |
| handshake_timeout_s | float, 5 | Identity/output discovery deadline |
| response_timeout_s | float, 1 | Normal command report wait |
| poll_interval_s | float, 2 | Runtime read-only station refresh |
| stale_after_s | float, 6 | No valid refresh response makes device stale |
| queue_limit | integer, 32 | Maximum pending normal operations |
| command_ttl_s | float, 2 | Maximum undispatched normal command age |

Timeout defaults are initial software values, configurable for commissioning.
No connect or power-on occurs on service startup. HTTP Connect uses server-discovered
selection IDs or the configured port, not arbitrary client-provided filesystem paths.

## Types and state fields

Use dataclasses/enums with snake_case fields; serialize enums as strings and times
as UTC ISO strings. Runtime deadlines use a monotonic clock. IDs are UUID strings.

| Type | Fields |
|---|---|
| SerialCandidate | selection_id, port, description, manufacturer, vid, pid, serial_number |
| DeviceSnapshot | connection, session_id, identity, firmware, port, last_seen, stale, outputs, error |
| OutputSnapshot | letter, mode, power, current_ma (nullable), fault (nullable) |
| LocoSnapshot | asset_id, address, desired_speed, desired_direction, reported_speed, reported_direction, functions, last_seen |
| FunctionState | desired (nullable bool), reported (nullable bool), pending |
| ControlSnapshot | revision, generation, emergency_latched, device, locomotives |
| Command | command_id, client_id, client_seq, generation, session_id, asset_id (nullable), kind, value, created_at, deadline |
| CommandResult | command_id, outcome, requested, reported (nullable), reason_code, detail |

Connection: disconnected/connecting/ready/error. Power: unknown/off/on/fault.
Command kind: main_power/throttle/function/stop/emergency_stop.
Outcome: confirmed/accepted_unverified/rejected/timeout/uncertain/superseded.
`confirmed` means station-reported, never observed locomotive motion.
Journal state is separate: pending/sent/finished/uncertain; outcome records the result.
Reported fields start null and are never copied from requested values.

Throttle speed is integer 0..126; direction forward/reverse. Function number 0..68;
function state must be an actual JSON boolean. Reject booleans as integers, nonfinite
numbers and unknown fields. Address is read from roster, never supplied by normal UI.

## Database changes

Migration 004 adds only these Phase 1 tables; no duplicate roster or persisted live
snapshot. Enable WAL outside an active transaction under initialization coordination.
Preserve foreign_keys and short BEGIN IMMEDIATE transactions. Update both services
to understand v4 in the same release; no editing live schema with one old service running.

| Table | Columns and constraints |
|---|---|
| control_command | command_id TEXT PK; client_id TEXT; client_seq INTEGER; generation TEXT; session_id TEXT; asset_id TEXT nullable FK asset; address INTEGER nullable; kind TEXT; payload TEXT JSON; state TEXT; outcome TEXT nullable; reason_code TEXT nullable; created_at TEXT; updated_at TEXT; UNIQUE(client_id,client_seq) |
| control_reservation | asset_id TEXT PK FK asset; owner_session TEXT; address INTEGER nullable; config_hash TEXT; state TEXT (held/uncertain); created_at TEXT; updated_at TEXT |

Index command updated_at and state for history cleanup/recovery. Keep completed
commands seven days and at most 10,000 records, cleaning periodically; never delete
pending/uncertain commands or reservations automatically. Deduplication is guaranteed
within the retained current session; old-session movement is rejected regardless.

Canonical config_hash covers control configuration, eligibility fields and required
relations/dependency configuration, with stable sorted JSON serialization. Descriptive
name/notes/media edits do not invalidate it. Reservation covers the locomotive and
its transitive required assets, acquired atomically in stable ID order. Each reserved
asset stores its own relevant hash. A node reservation is unnecessary in Phase 1.

On the first operating command, reserve before handing work to the runtime. Retain
reservation while the locomotive is under control, including speed zero because
functions and station state may still matter. Explicit Release is available in
connection/details controls and succeeds only with reported zero speed or confirmed
MAIN off, no pending work and no uncertain result. Selecting another locomotive
does not release the previous one. Roster.save compares protected fields for any
reserved asset and rejects incompatible edits with 409, allowing descriptive edits.

Service startup marks previous pending/sent commands and held reservations uncertain;
it never resends them. Reconciliation connects, explicitly turns MAIN off and waits
for a fresh applicable off report before releasing old operating reservations.
This is an operator action, not a startup side effect. Keep evidence if off cannot
be confirmed. Do not hold the global data lock while waiting for serial responses.

## Methods and ownership

| Module/type | Methods |
|---|---|
| discovery | list_candidates(), resolve_selection(selection_id, config) |
| SerialTransport | open(port, baud), read(max_bytes), write(frame), close(), is_open |
| Framer | feed(bytes) -> list[str], reset(); max frame 4096 bytes, discard malformed overflow |
| protocol | encode_main_power(on), encode_throttle(address,speed,direction), encode_function(address,number,active), encode_emergency_stop(), parse_frame(frame) -> DeviceEvent |
| ControlRepository | list_locomotives(), reserve(command), save_sent(id), finish(id,result), recover_sessions(), release(asset_id), prune_history() |
| ControlService | connect(selection), disconnect(), snapshot(), main_power(on,request), throttle(asset_id,speed,direction,request), function(asset_id,number,active,request), stop(asset_id,request), emergency_stop(request), resume(generation), release(asset_id), reconcile() |
| DeviceRuntime | start(), connect(selection), submit(command) -> Future, emergency_stop(command), snapshot(), disconnect(), shutdown() |

One runtime thread owns the serial object, framing and all writes. It alternates
bounded reads with outbound work; never drains an unlimited queue before reading.
HTTP threads wait on futures outside repository transactions. Use a priority stop
slot independent of the bounded normal queue. Only one response-correlated normal
operation is active; emergency actions interrupt waiting and invalidate pending
motion. Input reader must continue while waiting for responses. Snapshot locks are
short and never held around DB or serial I/O.

Normal pending throttle updates coalesce per asset; superseded requests receive
explicit superseded results. At dispatch recheck session/generation/config hash,
TTL and eligibility. On error close transport, fail/wake futures, clear old pending
work and mark affected state unknown/uncertain. Reconnect creates a new session.

## DCC-EX adapter

Use the predecessor framing/encoders with tests; redesign its controller lifecycle.
Handshake sends read-only status and output queries and requires DCC-EX identity.
MAIN operation also requires compatible observed output roles and fresh power state.
Do not open all USB candidates or infer CSB1 identity from bridge VID/PID alone.

MAIN power uses scoped `<1 MAIN>` / `<0 MAIN>`. Query TrackManager with `<=>`;
never send a role-setting command in Phase 1. Locomotive/function encoders use
native throttle/function commands; all-stop uses `<!>`. Native broadcasts lack
application request IDs: correlate by session, command type, address/output and
expected value, but never claim causal or physical proof from a matching broadcast.
Reference: [DCC-EX command reference](https://dcc-ex.com/reference/software/command-summary-consolidated.html).

Build fixtures for identity, output roles, scoped/global power, locomotive speed
byte/function reports, error and unknown frames. Decode reported speed bytes rather
than treating them as UI speeds. Unsupported function feedback remains unknown.
No matching report after a successfully written ordinary throttle/function gives
accepted_unverified; power-changing uncertainty blocks movement until refreshed.
Partial/failed write gives uncertain, with no automatic resend. Late reports may
refresh live state but do not rewrite a finished command's historical outcome.

## Eligibility, stop and multi-client rules

Operate only received/active DCC locomotives with valid address and satisfied
active/co-located dependencies. Detect conflicting active decoder addresses before
movement. Self-propelled MOW and consists require explicit later support; no silent
dispatch of multiple locomotives. MAIN must be freshly reported on.

Stop and power-off bypass inventory eligibility but require a usable serial session.
Stop uses the reserved execution address if inventory is inconsistent. Emergency
and ordinary locomotive stops both advance the control generation and discard
older pending motion, so an already-in-flight browser request cannot restart a
stopped locomotive. Ordinary stop does not latch emergency mode; clients refresh
the generation before issuing a new intentional movement. Emergency
stop remains callable while other requests are busy and clears pending movement.
It latches and changes generation atomically before transmission. Resume requires
the latest generation, creates another generation and does not restore speed.

Each page has a client_id and increasing client_seq. Repeated request IDs with the
same payload return the stored result; conflicting reuse returns 409. Reject older
sequence values for normal control from that client. Explicit stop requests may
always reach the stop path; duplicates remain idempotent. Session/generation checks
reject delayed motion after stop/reconnect, including from another browser tab.
Simultaneous valid operators are serialized; v1 does not add operator leases.

Changing direction while moving first stops using the previous direction and waits
for a zero-speed report. Until confirmed, reversal remains unavailable. Browser
disconnect does not imply train stop; physical emergency power-off remains necessary.

## HTTP API

Common write metadata: command_id, client_id, client_seq, generation, session_id.
Server validates IDs/sequence/types; database dedup checks both ID and client sequence.
Connect, disconnect, resume and release are lifecycle endpoints, not DCC packets.

| Method/path | Body or response |
|---|---|
| GET /health | service=asset_control, pid, instance, status; no claim of device readiness |
| GET /api/session | CSRF token, generation, session_id |
| GET /api/control | ControlSnapshot |
| GET /api/devices | candidate metadata/selection IDs |
| GET /api/locomotives | roster identity, address, eligibility and reason; no live location claim |
| POST /api/device/connect | selection_id optional |
| POST /api/device/disconnect | explicit request; marks unverified operation uncertain |
| POST /api/main/power | on: bool + metadata |
| POST /api/locomotives/{id}/throttle | speed, direction + metadata |
| POST /api/locomotives/{id}/functions/{number} | active: bool + metadata |
| POST /api/locomotives/{id}/stop | metadata |
| POST /api/emergency-stop | command metadata; not blocked by stale movement generation |
| POST /api/resume | current generation |
| POST /api/locomotives/{id}/release | current session/generation |
| POST /api/reconcile | explicit confirmation + current session/generation; MAIN off then release on report |

Responses: 200 completed request (inspect outcome), 400 invalid input, 403 CSRF,
404 unknown asset, 409 stale/busy/ineligible/conflicting request, 503 device unavailable,
504 required response deadline exceeded with explicit uncertain/timeout outcome.
No HTTP success is physical movement proof. No raw address override or serial strings.

Use a distinct `mtos_control_session` cookie, HttpOnly/SameSite Strict, to avoid
asset_manager cookie collisions across ports. Check origin on writes and require
CSRF; no wildcard CORS. Keep security headers and no-store API responses. Bind LAN
as requested; deployment assumes trusted local network, no Internet exposure.

## UI fields, functions and ergonomics

DOM IDs follow mockup: emergency, connection, power, connect, power-button,
device-trigger, device-options, loco-trigger, loco-options, identity, reverse,
forward, speed, speed-value, minus, plus, loco-stop, resume, functions, prev-bank,
next-bank and bank. Add details for device selection/reconciliation
and per-locomotive release. Preserve dark-green/amber theme, 48 px logo/triangle,
44 px primary targets, tabs before roster, Reverse left and Forward right.
Device and locomotive selection use in-page themed listboxes, not native iOS
select controls. The locomotive list contains only currently eligible
received/active locomotives with valid DCC configuration; ineligible inventory
does not appear as disabled clutter. Function buttons use a 4-by-4 keyboard per
16-key page. Its key sizing, spacing, dark face, amber active state and two-line
number/function-label treatment follow the proven predecessor CSB1 React UI. The one-second
poll updates persistent key elements rather than replacing them during touch;
keypress state changes immediately and then reconciles with the server response.
Pending keys remain fully visible and keep their active color instead of being
faded by generic disabled-button styling. Keys use a 1:1 aspect ratio with
increased internal padding.
Panel and button borders remain prominent against the dark theme.
Navigation labels use compact type and a horizontally scrollable tab row so Phase
3 can add Turnout and Signal.
The EX-CSB1 USB/serial connection and MAIN-power panel belongs only to locomotive
and later Programming views. Accessory views reuse the shell but replace it with
MQTT/network and ESP32-node status; they never imply a USB connection or track
power for ESP32 devices.

JS state: snapshot, selected_asset_id, function_page, pending_commands, client_id,
client_seq, generation, session_id, poll_timer, throttle_timer, fetch_generation.
Functions: api(), refresh(), render(), select_loco(), schedule_throttle(),
change_direction(), set_function(), stop_loco(), emergency_stop(), resume(),
change_function_page(). Use textContent for data and AbortController for stale reads.

Poll every 1 s while visible, refresh immediately on focus, prevent overlapping
polls and ignore old snapshots. Suspend polling while device-lifecycle or power
requests are in flight. Connect, disconnect and power controls immediately show
their pending operation; background snapshots cannot overwrite that feedback.
Request errors remain visible until another intentional command starts. Debounce
throttle at 100 ms with one in-flight
normal throttle and the latest pending value. Stops bypass debounce and clear it.
Keep stop controls independent of normal busy flags. On selection, clear pending
UI gestures and load that locomotive's state without sending a command.

16 functions per page: F0–15, F16–31, F32–47, F48–63, F64–68. Prev/next use solid
triangle arrows and accessible labels, disabled at endpoints. Function toggles
send explicit desired booleans, not server-side blind toggles. Unknown reported
state has no false reported styling. Because the DCC-EX locomotive broadcast only
reports F0–F15, the snapshot separately retains the last successfully transmitted
desired state for F0–F68; keyboard highlighting means commanded state, not physical
decoder confirmation. Keep detailed confidence information under details; visible
errors and uncertain state remain. Routine disconnected and power-off instructions
are represented by disabled controls instead of space-consuming messages. Location
is omitted because no live block detection exists. No simulation controls or sample
identities enter the production screen.

## Tests and acceptance scenarios

| Area | Required scenarios |
|---|---|
| Protocol | split/combined/noisy/oversized frames; malformed numbers; scoped MAIN vs PROG power; speed-byte direction decoding; F0/F68; unknown frames |
| Discovery | zero/one/multiple candidates; explicit selection; stable USB identity; busy port; wrong/silent device; handshake timeout |
| Runtime | read while command waits; bounded queue; throttle coalescing; stop during wait/full queue; failed/partial write; disconnect/reconnect; no replay; stale station |
| Concurrency | two clients; delayed pre-stop throttle; duplicate ID same/different payload; reverse while moving; stop remains available after eligibility change |
| Repository | migration v3 to v4; WAL; simultaneous init; atomic reservation/dependencies; permitted descriptive edit; rejected address/lifecycle edit; address collision; crash recovery; bounded cleanup preserves uncertain records |
| API | CSRF/origin; separate cookies; enums/scalars; missing asset; stale session/generation; error mapping; no raw serial/address override; health identity |
| UI | 320/393/430 px mobile and desktop; no horizontal overflow; triangle/tabs/order; 16-function paging through F68; disabled reasons; no location; keyboard focus; stop while busy; stale poll cannot overwrite latest state |
| Services | 5301 and 5302 coexist; bind 0.0.0.0; singleton owner; start/stop/restart/status; restore blocked while either service runs; failed startup cleans resources |

Fakes: injected serial transport, monotonic/UTC clock and deterministic runtime
step function. Automated tests never discover/open real USB or use the live DB.
Browser tests use seeded temporary rosters and fake adapter only. Verification
must distinguish executed browser tests from skips; manual iPhone review remains.

Supervised commissioning: record firmware and MAIN wiring; discover without writes;
confirm MAIN-only power on/off; test one known locomotive at low speed, direction at
stop and configured functions; stop/emergency/resume; reconnect with no restoration.
Record actual reports/capabilities and adjust fixtures without overstating feedback.
No PROG/CV writes in this checkpoint. Owner commits/pushes after review.
