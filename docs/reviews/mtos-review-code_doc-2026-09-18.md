# MTOS code, design and documentation review

Date: 2026-09-18

Scope: current local working tree, including modified and untracked code/docs.

Base commit observed: `c1adefa37a8bca0f399d2efa1afeb850a98265dc`. Findings are **not** limited to committed contents.

Disposition: **continue hardware-free development; address the P1 findings before commissioning the affected physical controls.**

## Assessment

The service decomposition is sensible and substantially implemented. Asset, Core, DCC, MC and HMI have separate entry points; Asset/Core/MC own separate SQLite files; browsers use Socket.IO; MC starts broker-offline by default. Naming, ports, database filenames and high-level ownership mostly agree with the current documentation.

The implementation and documents are **not yet synchronized at the behavioural-contract level**. Emergency ordering, configuration protection, execution-time fencing, recoverable command identity, independent adapter failures and bounded firmware execution have significant gaps. Some are accurately disclosed; others are described as implemented despite contrary evidence.

The existing suite passed **96 tests, with one optional browser test skipped**. An additional **22 isolated review probes reproduced the behaviours documented below**. The probes assert the observed faulty behaviours: passing them confirms findings, not correctness. No probe accessed production databases, serial ports, live MQTT, GPIO or running MTOS services.

The primary risk is **execution correctness and recovery, rather than RAM**. Additional RAM will not prevent throttle after emergency stop or repair lost execution identity. Keep the architecture, but treat the present system as an integrated development prototype rather than an implementation of every accepted control guarantee.

## Review method and limitations

Reviewed the context, README, documentation index, current ADRs and historical context; control-service architecture and Core/DCC/HMI/MC module contracts; operational startup/backup guidance; Python service/API/repository code; React command/state handling; ESP32 firmware/configuration; launchers, persistence and relevant tests.

| Validation | Result |
|---|---|
| `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider` | 96 passed, 1 skipped; 8.07 seconds |
| Additional isolated probes using temporary SQLite databases and fakes | 22 reproduced behaviours; final run 0.60 seconds |
| Python AST parsing under `src/` and `tools/*.py` | 42 files parsed successfully |
| Real browser exercise | Not run; existing optional browser test is opt-in and covers the roster, not HMI operation |
| Frontend rebuild/typecheck | Not run; `node` unavailable on shell PATH |
| PlatformIO build/firmware simulation | Not run; `pio` unavailable on shell PATH; node headers remain templates |
| Live MQTT integration | Not run; `paho` absent from the selected project interpreter despite being declared in requirements |
| SBC memory/latency soak or electrical commissioning | Not run |

Probe source was retained outside the repository in this review task's `work/test_review_probes.py`. The evidence appendix identifies every probe and its observed result. Firmware findings are source-level findings, not claims of measured physical failures. No production implementation or existing documentation was repaired during this review. Source line numbers refer to the reviewed working tree and will move with subsequent edits.

Severity: **P1** = control/recovery defect to fix before affected physical commissioning. **P2** = substantive integration, reliability, deployment or documentation defect to resolve before claiming its contract. No unconditional production P0 is asserted.

## P1 findings

### R01 — Emergency stop does not invalidate already admitted motion

**Sources:** [Core service](../src/mtos/core/service.py), lines 65–74, 85–104, 177–187, 219–238; [DCC service](../src/mtos/dcc/service.py), lines 116–143; [station](../src/mtos/control/dcc/station.py), `_operating` and emergency path.

Core checks its emergency latch before lease acquisition, without synchronizing that check with stop or rechecking at dispatch. A throttle paused inside lease acquisition can continue after emergency stop. A deterministic threaded probe produced **emergency followed by throttle while the Core latch remained true**.

Browser `generation` is discarded by `hmi_command()`. The published generation is just `session_id:epoch`, unchanged by emergency, ordinary stop, resume or device reconnect. An obsolete generation was accepted after resume. DCC validates the session/fence before waiting on the station operation lock, not immediately before serial transmission, so already waiting commands cannot be invalidated reliably.

**Mismatch:** ADR-009 requires stale-generation/session rejection and removal of queued motion. This is additional to the explicitly deferred emergency bypass.

**Fix/acceptance:** implement a real operation generation and serialized dispatch barrier; invalidate queued work on stop/disconnect; revalidate authority at final send. Test paused lease acquisition, queued serial work, old browser requests and resume/reconnect together. No old motion may be transmitted after the stop barrier.

### R02 — Emergency traffic shares normal admission and HTTP bottlenecks

**Sources:** [HMI admission](../src/mtos/hmi/service.py), lines 51–74; [HMI tasks](../src/mtos/hmi_app.py), lines 103–122; [server](../tools/serve.py), line 60; [Core emergency](../src/mtos/core/service.py), lines 219–232.

HMI rejects emergency stop when the browser's normal outstanding-command limit is reached; reproduced with a one-slot limit. Core/DCC run four Waitress workers. Ordinary requests wait synchronously for downstream work, so saturation can queue the emergency HTTP request before it reaches the independent serial write path. Core also journals before contacting DCC, allowing database contention to delay stopping.

**Fix/acceptance:** reserve emergency admission/execution capacity at every hop. Define best-effort stopping when persistence is unavailable. Saturate normal traffic in a process-level test and measure stop latency. Retain the documented caveat that Core-unavailable bypass is not implemented.

### R03 — Normal shutdown can remove the watchdog before trains are stopped

**Sources:** [coordinator](../tools/mtos_services), lines 45–48; [stop launcher](../tools/service.py), lines 73–82; [DCC shutdown/watchdog](../src/mtos/dcc/service.py), lines 101–114, 145–156; [shutdown guide](operations/service-startup.md).

The coordinator SIGTERMs HMI, Core, MC and DCC in quick succession. It does not request/await all-stop or allow the six-second watchdog interval before DCC exits. DCC `close()` only disconnects. `atexit` registration is not an explicit SIGTERM handling contract.

Thus `mtos_services stop` can leave the externally powered command station executing its last motion instruction after the UI and watchdog disappear. This was established by source inspection; no live shutdown was attempted.

**Fix/acceptance:** inhibit ingress, request all-stop, record confirmation/uncertainty, then close adapters. Handle SIGTERM with bounded draining and test using fake serial/process termination. Do not equate software shutdown with track power removal.

### R04 — Leases do not protect component wiring or calibration

**Sources:** [Roster save](../src/mtos/roster.py), lines 449–467; [Core lease scope](../src/mtos/core/service.py), lines 130, 254–267; ADR-009 lease contract.

The protected comparison omits `components`. The review acquired a T001 lease and successfully changed its servo channel from 0 to 5. Calibration endpoints are equally unprotected. Core leases only the directly addressed asset, not its associated node/configuration/dependency closure. Existing lifecycle-link checks cover some dependencies but not all configuration affecting the physical operation.

**Fix/acceptance:** define one control-configuration fingerprint including components, mapping, calibration and relevant node/dependency configuration. Atomically protect the necessary asset set. Exercise actual API edits against every protected path while still allowing descriptive edits.

### R05 — Logical reservations do not prevent duplicate physical resources

**Sources:** [Asset leases](../src/mtos/roster.py), lines 227–279; link validation at 564–588; [Core reservations](../src/mtos/core/repository.py), lines 108–126; [MC design](architecture/mtos-mc-module.md), admission section.

Two received/active locomotives at the same DCC address can be created and leased together; reproduced with L001/L002 at address 28. Reservations keyed by asset ID do not conflict even when the physical decoder address does. There is no cross-asset uniqueness enforcement for node/bus/channel assignments either.

The MC document states that duplicate physical-output mappings are enforced by Asset/Core. The reviewed workflow does not enforce this.

**Fix/acceptance:** validate and reserve physical resource keys as well as logical IDs. Reject ambiguous active decoder addresses and conflicting output mappings. Any intentionally shared decoder/consist requires an explicit policy. Test two distinct IDs targeting one physical resource.

### R06 — Asset cannot persist the configuration Core/MC consumes

**Sources:** [Control dataclass](../src/mtos/assets/model.py), lines 150–172; [Asset parsing](../src/mtos/roster.py), lines 90–127; [Core stationary path](../src/mtos/core/service.py), lines 125–143; [Asset projection](../src/mtos/app.py), lines 204–222; `FakeStationaryAsset` in [Core tests](../tests/test_core_service.py).

Core reads top-level `control.configuration_revision`, `control.actions` and `control.resources`; the real Control dataclass accepts none. Saving `configuration_revision` raises TypeError. The test fake injects a shape the real Asset API cannot save.

Fallback to general asset revision makes a label edit change the required installed node revision. Different assets sharing a node can demand incompatible revisions. Putting values under the supported `attributes` object does not work because consumers read top-level keys. Defaulting every machine to `operate` also bypasses the declared-action contract.

**Fix/acceptance:** implement one persisted schema for hardware configuration revisions, commissioned actions and resources. Separate configuration revision from descriptive revision. Test the whole path beginning with assets created through the real API.

### R07 — Core loses the information needed to recover MC response loss

**Sources:** [Core stationary dispatch](../src/mtos/core/service.py), lines 127–150; [Core journal/reconcile](../src/mtos/core/repository.py), lines 20–35, 92–106; [MC snapshot](../src/mtos/mc/service.py), lines 91–98; [recent executions](../src/mtos/mc/repository.py), lines 100–103.

Core generates an execution ID but persists only the requested value before sending. Execution identity becomes durable in Core only if the MC reply arrives. If MC accepts and the reply is lost, Core records uncertain with no result/execution identity. This was reproduced even when MC later reported completion.

Reconciliation scans only accepted Core rows with a result, using MC's most recent 100 executions. It excludes missing-response cases, older omitted executions and already uncertain rows. A second probe showed an MC resolution from uncertain to completed leaving Core permanently uncertain.

**Fix/acceptance:** persist the immutable full dispatch identity/envelope before sending. Query all unresolved executions by identity rather than recent-list projection. Reconcile uncertainty monotonically. Test lost replies, restart, more than 100 executions and manual resolution.

### R08 — Old queued work dispatches under new authority; watchdog revival is too permissive

**Sources:** [MC session/recovery](../src/mtos/mc/service.py), lines 53–75; scheduler at 167–202; [DCC heartbeat](../src/mtos/dcc/service.py), lines 93–99; ADR-009 failure contract.

MC checks whether the current Core is alive but does not compare queued payload authority with that Core. A request queued under epoch 4 was published after a different Core established epoch 5. Restart also preserves queued work without explicit reauthorization.

DCC/MC allow ordinary same-session heartbeat to clear stale status. For DCC, a probe then executed throttle without the new fenced handshake/reconciliation required by the target contract. The existing DCC test explicitly expects this weaker revival behaviour.

**Fix/acceptance:** quarantine/cancel old unsent work at authority changes, revalidate at dispatch, and require explicit recovery after watchdog loss. Decide whether any queued intent can be reauthorized. A live new Core is not automatic approval for old commands.

### R09 — MC rejects normal duplicate events and matching late completion

**Sources:** [MC event handling](../src/mtos/mc/service.py), lines 205–222; [Paho callback](../src/mtos/mc/mqtt.py), line 41; MC recovery contract.

A repeated accepted event raises conflict. Matching completed evidence for an uncertain job also raises conflict. Missing intermediate events prevent later completion from advancing state. These cases are foreseeable with duplicate delivery, reconnects and the currently documented QoS 0 publisher.

The Paho callback forwards into the handler without an application exception boundary. Errors therefore escape callback processing; the actual effect on a live network-loop thread was not tested because Paho is absent. This report does not claim a measured client-thread crash.

**Fix/acceptance:** make repeated evidence idempotent, handle contradictions without disrupting message processing, and define late-evidence transitions from uncertainty. Retain dispatch-time boot/session identity, not just current node projection. Test the callback adapter with repeated, missing, delayed and reordered evidence.

### R10 — MC cancellation and state/gate changes race across threads

**Sources:** [MC scheduler/cancel/reconcile](../src/mtos/mc/service.py), lines 167–236; constructor at 53–61; [repository transition](../src/mtos/mc/repository.py), lines 105–115.

Only some entry points acquire `_lock`. Scheduler, MQTT callbacks, node updates and HTTP cancellation/reconciliation mutate state/gates concurrently. SQL transitions do not condition updates on the expected previous state.

A deterministic probe captured a queued row, cancelled it, then resumed dispatch: the cancelled row became dispatched and was published. Restart restoration reconstructs uncertain servo/machine gates but omits the uncertain signal's per-node gate; separately reproduced.

**Fix/acceptance:** use a single state owner or consistent locking plus transactional compare-and-set transitions. Restore every resource class. Test cancel/dispatch, reboot/completion, event/timeout and signal-restart interleavings.

### R11 — Incoming firmware commands overwrite an active execution's identity

**Sources:** [ESP32 firmware](../firmware/esp32_node/src/main.cpp), lines 93–115; [host scheduler](../src/mtos/mc/service.py), lines 183–190; existing simultaneous signal/servo test in [MC tests](../tests/test_mc_service.py).

`acceptCommand()` replaces global `executionId`/`commandHash` before checking whether the runner is busy. A second request publishes busy and clears the execution ID while the original physical runner continues. The terminal-cache replay branch similarly overwrites/clears active globals.

This is reachable in intended use: MC permits a signal during servo movement on the same node, whereas firmware has a single shared runner and rejects that signal. An active command duplicate also triggers the defect. Completion can then lose its original identity, stranding the host resource permit. A duplicate rejection must not be mistaken for proof the original execution stopped.

**Fix/acceptance:** use separate immutable active context and incoming/rejection context; replay active duplicate state without mutation. Implement concurrent signal handling or consistently serialize all node work. Test duplicate and signal arrival during a servo operation at firmware level.

### R12 — Interrupted turnout movement leaves a valid-looking stale NVS position

**Sources:** [ESP32 firmware](../firmware/esp32_node/src/main.cpp), lines 124–130, 169–170; MC double-slip/fail-closed contract.

NVS retains the previous complete position throughout movement and updates only after all actuators finish. Reboot mid-sweep or failure after the first double-slip servo therefore leaves the old position marked valid. The next operation starts from that old PWM endpoint, despite unknown/partial physical position. Timeout reports failed without invalidating the recorded position.

**Fix/acceptance:** durably mark unknown/in-progress before any actuation and commit a new commanded endpoint only after full cleanup. Record double-slip component progress and require evidence/supervised recommissioning after interruption. Test resets at each movement stage; do not confuse timed completion with sensed position.

### R13 — Firmware ignores producer epoch and can replace authority during execution

**Sources:** [MC handshake](../src/mtos/mc/service.py), lines 121–126; [firmware validation](../firmware/esp32_node/src/main.cpp), lines 99–118.

MC sends `mc_epoch`, but firmware never checks it. Any matching-node/boot handshake with a plausible timestamp replaces producer session and clock baseline, even mid-execution. Delayed older handshakes can roll authority back. Later events use the newly global producer session instead of the accepting job's session. All non-handshake schemas enter ordinary command handling without requiring `mtos.mc-command.v1`.

**Fix/acceptance:** validate schema and monotonic producer epoch; define same-epoch idempotency and reject older handshakes. Pin active execution identity to its accepting session. Require an explicit reconciliation rule before replacing an active owner. Test stale handshakes and MC restart during actuation.

### R14 — Firmware does not demonstrate bounded, calibrated nonblocking execution

**Sources:** [firmware](../firmware/esp32_node/src/main.cpp), `serialCommissioning`, lines 141–173; [firmware README](../firmware/esp32_node/README.md).

Servo PWM advances three counts per loop iteration, without a configured step interval. Sweep rate depends on incidental I2C/network/loop timing rather than a calibrated duration. Per-servo timeout is a fixed 2.5 seconds.

Relay cutoff, PWM watchdog, flashing and signal handling occur after `Serial.readStringUntil`, network connection and MQTT processing. The serial read is blocking, and reconnect work shares the output-timing thread. No independent cutoff bound is established; a stalled call can delay relay opening or PWM cleanup. Exact network delays remain unmeasured.

**Fix/acceptance:** implement per-actuator monotonic step schedules, incremental serial input and output deadlines independent of blocking reconnect work. Validate reset/OE protection. Test partial serial input and unavailable broker during relay pulses and movement, then measure the real timing.

### R15 — DCC readiness and reported state overstate device evidence

**Sources:** [station](../src/mtos/control/dcc/station.py), lines 51–90, 145–175, 194–242; [Core throttle](../src/mtos/core/service.py), lines 177–187.

Handshake waits for both identity and MAIN mode but checks only identity at timeout. An identity-only fake was declared ready with no MAIN mode and accepted nonzero throttle. Core/station motion paths do not require known MAIN mode/power; that protection exists only in the browser.

There is no elapsed-time station freshness check/periodic refresh. An open but silent serial device can remain ready indefinitely. A later track report reclassifying MAIN as another mode is ignored by the MAIN-only update branch, retaining stale capability state.

Emergency write sets the reported locomotive speed to zero without a device report; reproduced with fake serial emitting no emergency acknowledgement. This violates desired-versus-reported semantics.

**Fix/acceptance:** fail readiness closed, enforce motion eligibility in the backend, invalidate changed track roles, implement freshness, and separate commanded stop from observed speed. Test identity-only, silence, role changes and unacknowledged stop.

## P2 findings

### R16 — Acceptance and uncertainty are presented as completion

**Sources:** [frontend API](../frontend/asset_control/src/api.ts), lines 56–69; [React](../frontend/asset_control/src/App.tsx), lines 153–158, 174–249; [HMI execution](../src/mtos/hmi/service.py), lines 77–90; [Core dispatch](../src/mtos/core/service.py), lines 281–285.

Frontend command promises resolve on HMI acceptance. Pending lifecycle/function state is cleared after an immediate snapshot, before execution necessarily finishes. Later failures show a generic message instead of rolling back the corresponding optimistic command reliably.

HMI labels every result except queued as `command.completed`, including DCC `outcome='uncertain'`; reproduced. Core also journals returned uncertain DCC outcomes as completed. This can invite repeated power-on clicks while actual state is unknown.

**Fix:** correlate acceptance/sent/terminal events by command ID, retain pending state until resolution, and preserve failed/uncertain semantics end to end. Test delayed results, uncertain power and asynchronous function rejection in a real browser.

### R17 — HMI retains stale ready state and lacks coherent stream recovery

**Sources:** [HMI monitor](../src/mtos/hmi_app.py), lines 124–136; [snapshot](../src/mtos/hmi/service.py), lines 37–40; [React subscriptions](../frontend/asset_control/src/App.tsx), lines 153–158; [socket adapter](../frontend/asset_control/src/api.ts).

Core snapshot errors are swallowed, leaving the last ready display. React does not treat socket disconnect/freshness as operational state or enforce event sequence/control-session recovery. State changes do not themselves increment HMI event sequence. Pending operations discard whole incoming snapshots, including potential emergency changes.

Speed/direction widgets are local state rather than selected locomotive reports; selection resets displayed speed to zero. Lists load once, so newly active assets/hotplugged devices need reload. Changing selected locomotive also does not cancel an already scheduled throttle timer.

**Fix:** expose unavailable/stale capability state, require a fresh snapshot before normal control, version snapshots coherently, merge pending UI fields without discarding safety state, and cancel delayed intents on selection/session changes. Test reconnect, reordered state and two browsers.

### R18 — Adapter failures are coupled and adapter restart lacks recovery

**Sources:** [Core start/heartbeat/snapshot](../src/mtos/core/service.py), lines 34–74, 245–252; [Core readiness](../src/mtos/core_app.py), lines 58–61.

MC snapshot failure aborts the complete HMI snapshot even if DCC is healthy; reproduced. Either heartbeat failure sets both adapters unready. Successful heartbeat restores `dcc_ready` but not `mc_ready`, and `/ready` ignores MC readiness. Restarted adapters lose their Core session; Core continues heartbeats without establishing a replacement session.

**Fix:** maintain independent capability state, permit partial snapshots, and define fenced per-adapter recovery/reconciliation. Test MC failure with DCC operating, the reverse, and standalone adapter restart. If recovery is intentionally manual, expose and document the action.

### R19 — Advertised bounds do not bound actual tasks or socket backlogs

**Sources:** [HMI admission](../src/mtos/hmi/service.py), lines 63–74; [task spawn](../src/mtos/hmi_app.py), line 121; [server](../tools/serve.py), lines 54–60; ADR-009 limits table.

Outstanding work is a set of command IDs, but every admission launches a task. Repeating one ID with increasing sequences admitted 100 requests while accounting remained one against the configured 32 limit. Disconnect also discards accounting while tasks continue.

The event-history deque does not bound per-client send queues; no 256-event/1-MiB slow-client policy exists. Incoming Socket.IO size limits do not bound outgoing snapshots. Core lacks the specified explicit 256 normal queue/emergency slot. HMI uses Werkzeug with `allow_unsafe_werkzeug=True`, not the chosen/tested production runtime described by ADR-009.

**Fix:** independently bound tasks, deduplicate before spawning, enforce outbound/backpressure limits and choose/test production serving. Exercise duplicate IDs, disconnect churn and slow readers before treating memory estimates as sustained-load bounds.

### R20 — Lease expiry/reconciliation/release has no supported lifecycle

**Sources:** [Roster lease and protection](../src/mtos/roster.py), lines 227–279, 449–467; [lease client](../src/mtos/core/clients.py), lines 84–90; [Asset API](../src/mtos/app.py).

Expiry is stored but never transitions held leases to expired-pending-reconciliation; there is no periodic renewal or safe release. Any lease row keeps protected edits blocked, and Core reservations have no release path. Higher-epoch acquisition replaces ownership without checking reconciliation evidence. Legacy reservations can continue blocking edits too.

**Fix:** implement renew/expire/reconcile/release with explicit evidence and an operator recovery interface. Never equate elapsed time with safe physical state. ADR-009 already discloses missing renewal/release; add its practical consequence: ordinary operated assets cannot be safely unlocked through the supported API.

### R21 — RPC deadlines are shorter than legitimate hardware operations

**Sources:** [JSON client](../src/mtos/core/clients.py), lines 19–37; [station handshake](../src/mtos/control/dcc/station.py); [browser ack timeout](../frontend/asset_control/src/api.ts).

Every internal HTTP call times out after two seconds, including HMI→Core and Core→DCC, while DCC allows a five-second handshake. Queueing/nested work adds delay. Caller timeout does not cancel downstream execution, so a device operation can finish after failure/uncertainty was reported.

**Fix:** use durable asynchronous acceptance/result lookup or coordinated deadline budgets with well-defined pre-dispatch cancellation. Test successful handshakes longer than two seconds and completion after client timeout; preserve command identity throughout.

### R22 — MC expiry validation and lost-result handling can strand the queue

**Sources:** [request validation](../src/mtos/mc/models.py), lines 55–71; [scheduler](../src/mtos/mc/service.py), lines 167–175, 245–254.

Expiry is only checked as a nonempty string. A malformed date is accepted, then raises every time the scheduler reaches it; the loop silently swallows errors. A probe confirmed a valid job behind it never dispatches. Naive/timezone-aware comparison is another failure case.

There is no execution deadline after dispatch. Lost completion can remain dispatched/started indefinitely. The servo gate stays conservatively held, but reconciliation accepts only uncertain state, leaving no direct supported recovery for that stranded state. This is more consequential than the disclosed missing stale-state label alone.

**Fix:** parse/normalize expiry at admission, isolate invalid rows, derive execution deadlines, transition missing evidence to uncertain without freeing gates, and expose supervised recovery. Test malformed/naive timestamps and lost completion without reboot.

### R23 — Accessory readiness does not compare the selected asset's configuration

**Sources:** [node readiness](../src/mtos/mc/service.py), lines 256–262; dispatch at 175–177; [React readiness](../frontend/asset_control/src/App.tsx), lines 257–260; [HMI module](architecture/mtos-hmi-module.md).

Node-ready checks merely that installed revision is an integer. React checks broker/node readiness but not selected-asset revision or stale Core authority. A probe produced ready=true for a node while a mismatched-revision command could not dispatch. The enabled UI can only queue/expire that operation.

**Fix:** expose per-asset capability readiness with revision, authority, conflicting execution and disabled reason. Keep node liveness separate. Correct the documentation's configuration-matched-ready claim until implemented.

### R24 — A known default token grants privileged leases through the LAN listener

**Sources:** [Asset token defaults/internal routes](../src/mtos/app.py), lines 26–54, 224–232; [coordinator](../tools/mtos_services), line 29; other app factories.

Default startup uses literal `development-only` and neither requires nor generates a private credential. Asset exposes internal leases on its LAN listener. A probe using that token acquired a lease under an arbitrary high-epoch session without browser CSRF/session state. This can lock legitimate users out and defeats the chosen Core-only authority boundary.

This finding does not demand user accounts for the intentionally trusted-LAN product; it concerns its separate internal service boundary.

**Fix:** provision a private deployment token or fail closed; isolate privileged Asset routes on loopback/equivalent access control. Document distribution and validate production settings.

### R25 — Backup consistency and restore authority are not defined across services

**Sources:** [backup](../src/mtos/backup.py), lines 77–86; [Core](../src/mtos/core/repository.py) and [MC](../src/mtos/mc/repository.py) independent writers; [operations](operations/roster.md).

Backup locks Asset, then copies Asset/Core/MC sequentially. Core/MC do not share that lock, so their transactions and physical effects may advance between copies. Checksums/integrity verify individual files, not one common operational checkpoint. Restore rolls durable epochs/fences back relative to surviving devices, without a restore-specific authority/reconciliation policy.

**Fix:** quiesce dispatch for a coordinated snapshot or define backups as crash-recovery input that mandates reconciliation. Specify epoch handling and old queued work after restore. Test snapshot/restore during acceptance/completion with fakes. This is not a claim of SQLite file corruption.

### R26 — Photo processing holds the write lock needed by control admission

**Sources:** [media insertion](../src/mtos/roster.py), lines 660–705; [optimizer](../src/mtos/image_optimizer.py); lease transaction at line 239 of Roster.

Media optimization runs inside the global Asset write transaction. A slow image on an A20 can block lease acquisition beyond the internal two-second timeout. Waiting uploads can occupy all Asset workers. The useful new pixel cap/serialization does not isolate control latency, and the optimizer semaphore cannot bound callers already waiting on the earlier filesystem lock.

**Fix:** optimize to a staged file outside the transaction, then briefly lock/revalidate/register. Bound upload admission before scarce locks/workers. Measure lease/control latency during the largest permitted upload.

### R27 — Launchers do not establish complete lifetime ownership or safe rollback

**Sources:** [server initialization](../tools/serve.py), lines 24–53; [lifecycle launcher](../tools/service.py), lines 39–83; [coordinator rollback](../tools/mtos_services), lines 49–63; [serial open](../src/mtos/control/dcc/transport.py), lines 24–29.

Factories create/migrate databases and start threads before taking the service-lifetime restore lock. A restore can overlap those initial effects. Launcher locks cover launcher execution, not child lifetime; runtime has no exclusive adapter-owner lock, and serial open does not request exclusivity.

Startup unwind includes already-running services, so a later failure can stop a service this invocation did not create. Stop/status treat a failed health request as stopped, leaving a wedged process alive while restart attempts another instance.

**Fix:** acquire restore/service ownership locks before side effects and retain them in the child. Track process identity independently of health. Roll back only newly started services. Test start/restore races, hung health and partial-stack startup failure.

### R28 — Operating asset lists silently truncate at 100 per family

**Sources:** [Asset operating lists](../src/mtos/app.py), lines 182–220; [Roster search](../src/mtos/roster.py), lines 394–418.

Endpoints request limit=100 and ignore pagination/total. More than 100 eligible locomotives or stationary assets in a family are never presented in HMI. The documented total roster exceeds 100, but this review did not inspect the current live active count.

**Fix:** paginate all eligible results or expose an explicit supported limit/error. Test at least 101 active eligible assets. This is a correctness/scale boundary independent of available RAM.

## Documentation synchronization matrix

| Document/claim | Actual status | Required action |
|---|---|---|
| README/context: five normal services, ports, owned databases | Substantially accurate | Retain; qualify behavioural completeness |
| ADR-009 separates targets from implementation | Good and useful | Add the newly established deviations below |
| Core module: lease/journal/dispatch and recovery | Happy path exists; R01/R06/R07 remain | Describe actual limits; implement durable recovery |
| Protected component/channel/calibration changes | Not protected, R04 | Fix code and add real API tests |
| MC design: expiry/output-map conflicts enforced by Asset/Core | Incorrect, R05/R20 | Remove implemented claim until enforced |
| MC callbacks enqueue to a single scheduler owner | They mutate shared state directly, R10 | Implement ownership or documented locking |
| Matching late evidence resolves uncertainty | Incorrect, R07/R09 | Implement transitions and reconciliation |
| HMI configuration-matched ready state | Incorrect, R06/R23 | Per-asset readiness and disabled reasons |
| Failed heartbeat is visible and prevents ordinary control | Overstated, R01/R08/R17/R18 | Enforce and publish stale capability state |
| Reverse-order shutdown obtains watchdog stop | Not assured, R03 | Explicit stop-before-exit policy |
| Firmware nonblocking/bounded/fail-closed position claims | Incomplete, R11–R14 | Separate source intent from verified behaviour |
| ADR-009 production HMI runtime | Actual launcher enables Werkzeug | Select/test runtime and update docs |
| Earlier review: decoded-pixel/concurrency controls missing | Now stale: 25M pixel cap and serialized optimizer exist | Mark historical/resolved; retain R26 latency issue |
| Earlier 0.5–0.9 GiB estimate | Still planning, not measurement | Qualify sustained behaviour after bounds/load tests |
| Historical monolithic documents | Correctly grouped as historical | Do not mistake superseded topology for a new defect |

Additional textual corrections:

- MC documentation says dispatch is recorded after successful client enqueue; code records dispatched **before** publish. That ordering is sensible for uncertainty, but prose should match.
- Startup guide says the railroad is not energized after startup. State instead that MTOS has not energized it and actual hardware power is unknown until observed.
- ADR-009 still calls the A20 constraint obsolete in alternatives, despite its revised measurement-based, host-neutral introduction.
- The MC diagram labels HMI–Core Socket.IO. Current Socket.IO is browser–HMI; HMI–Core uses HTTP/JSON.
- The earlier design review is correctly introduced as historical, but its resource discussion still reads as current when describing now-fixed image limits. Add an explicit implementation update.

## Accurately disclosed unfinished work

These are important release constraints, but not newly discovered documentation misrepresentations:

- Firmware publishes node events/status at QoS 0; QoS 1 command subscription does not satisfy the event contract.
- Active execution duplicate replay is missing. R11 adds a separate, more serious context-corruption consequence to the already disclosed busy response.
- Periodic lease renewal/release, terminal/event pruning, systemd units and the Core-unavailable emergency bypass are explicitly pending.
- Automatic stale-dispatch uncertainty is pending; R22 explains the resulting recovery gap.
- Full HMI diagnostics and replay/resynchronization remain incomplete.
- PlatformIO compilation, broker ACL/session validation, sustained-load tests and physical commissioning remain pending.
- CV/PROG, occupancy, routes, interlocking and AI are deliberately deferred. Their absence is not itself a defect in this increment.

## Design decisions still needed

1. **Operator ownership:** leases identify the Core service, not an operator/browser. Two browsers can issue conflicting throttle commands using the same Core lease. Define exclusive/shared control, takeover, idle expiry and priority before claiming producer arbitration.
2. **Emergency scope:** the button says all locomotives; stationary commands ignore the Core latch. Decide whether this is intentionally locomotive-only or a system emergency affecting queued accessories. Do not abort a physical sequence without a defined cleanup policy.
3. **One command lifecycle vocabulary:** distinguish admission, sent, completion, failure and uncertainty consistently. Known pre-dispatch validation failure should not become an uncertain physical operation merely because it is an HTTP error.
4. **Configuration provisioning:** define the Asset-owned node projection, mapping/mask uniqueness, commissioned actions, installed revision acknowledgement and descriptive-versus-hardware changes. Manually edited header templates do not alone implement the contract.
5. **Restore authority:** define epoch/fence behaviour after database rollback and reconciliation against external nodes before operation resumes.
6. **Independent bounds:** limit tasks, send queues, SQL transaction duration, image work, history and logs. A bounded list does not bound all work associated with it.

## Reproduction evidence and test gaps

All probes used temporary data and fake transports; names below omit the common `test_` prefix. The cancellation probe intentionally interleaves cancel between queue selection and dispatch. The throttle probe uses thread events to pause lease acquisition. They establish missing synchronization deterministically rather than through probabilistic load failures.

| Probe | Observed result | Finding |
|---|---|---|
| `old_browser_generation_is_accepted_after_emergency_resume` | Old generation accepted; generation unchanged | R01 |
| `throttle_already_in_core_can_dispatch_after_emergency` | Throttle after emergency while latched | R01 |
| `watchdog_accepts_same_session_heartbeat_without_reconciliation` | Same authority resumes after watchdog | R08 |
| `leased_component_mapping_is_editable` | Leased channel changed successfully | R04 |
| `mc_control_configuration_cannot_be_saved_in_asset` | Real schema rejects MC revision field | R06 |
| `duplicate_active_decoder_addresses_are_accepted_and_leased` | Two assets lease one decoder address | R05 |
| `default_internal_token_accepts_lease_on_asset_lan_app` | Known credential authorizes privileged lease | R24 |
| `old_queued_mc_execution_dispatches_under_new_core_session` | Old job published under new authority | R08 |
| `mc_duplicate_nonterminal_event_raises` | Duplicate accepted event raises conflict | R09 |
| `uncertain_mc_job_cannot_accept_matching_completion` | Late matching completion rejected | R09 |
| `mc_cancel_can_race_with_dispatch` | Cancelled operation dispatched | R10 |
| `mc_restart_loses_uncertain_signal_gate` | Uncertain signal has no restored node gate | R10 |
| `core_loses_mc_execution_identity_after_submit_response_loss` | Uncertain Core row lacks execution identity | R07 |
| `core_does_not_reconcile_a_later_resolution_of_uncertain_mc` | Resolved MC job stays uncertain in Core | R07 |
| `hmi_duplicate_ids_bypass_outstanding_bound` | 100 admissions counted as one ID | R19 |
| `station_ready_without_main_and_accepts_throttle` | Identity-only connection accepts motion | R15 |
| `emergency_write_overwrites_reported_speed_without_report` | Observed speed overwritten without evidence | R15 |
| `invalid_mc_expiry_is_accepted_then_blocks_dispatch_loop` | Bad timestamp blocks later work | R22 |
| `mc_failure_prevents_dcc_hmi_snapshot` | MC error hides ready DCC projection | R18 |
| `hmi_calls_uncertain_dcc_outcome_completed` | Uncertain emitted as completed | R16 |
| `hmi_emergency_is_rejected_at_normal_capacity` | Emergency rejected at normal limit | R02 |
| `signal_mapping_revision_is_not_in_hmi_readiness` | Ready node cannot dispatch selected revision | R23 |

Why existing tests pass despite these findings:

- Core tests supply unsaveable real-world configuration via fake dictionaries.
- The DCC watchdog test explicitly expects weaker recovery than ADR-009 specifies.
- Fake MQTT only records publication; it does not run the firmware state machine, so simultaneous signal/servo tests miss firmware rejection and identity corruption.
- Tests are predominantly sequential. Lease/stop, cancel/dispatch, response loss and stale-generation interleavings are absent.
- The optional actual-browser test covers roster forms, not the new HMI result lifecycle or multiple operators.
- Host pytest does not compile or execute ESP32 code.

## Recommended correction sequence

### 1. Stop and authority guarantees

Address R01–R03, R08 and R15 first. Prove no older motion is sent after the stop barrier; saturation cannot starve emergency; stale authority cannot revive through ordinary heartbeat; shutdown attempts stop before withdrawing DCC. Preserve uncertainty rather than claiming physical confirmation.

### 2. Real configuration and reservations

Address R04–R06 and R20/R23. Create configuration through the real Asset API in tests. Cover multiple assets per node, descriptive changes, protected calibration, duplicate physical resources and safe release. Use a validated commissioned node projection.

### 3. Durable execution and firmware protocol

Address R07, R09–R14 and R22. Persist identity before dispatch; make transitions atomic/idempotent; reconcile every unresolved execution. Compile/simulate firmware, resolve QoS/duplicates and test network loss during each output phase before physical MQTT operation.

### 4. HMI and deployment

Address R16–R19 and R21/R24–R28. Add real browser/process tests for delayed results, stale state, saturation, independent restarts, rollback, coordinated backup/restore and image contention. Validate internal tokens and production serving.

### 5. Hardware and resource qualification

After behavioural corrections, perform a representative fake-load soak on Cubietruck/Pi, then supervised hardware tests. Record process PSS/RSS, available memory, swap, CPU/IO, command latency and emergency latency. Include maximum permitted upload, slow readers and reconnect bursts. The earlier 0.5–0.9 GiB normal-operation estimate remains plausible planning, but present task/backlog gaps prevent treating it as a verified upper bound.

## Final disposition

Retain the service architecture. Correct implementation and corresponding claims together, with regression evidence for each guarantee. The 15 P1 and 13 P2 findings above identify concrete work before the affected capabilities can be considered complete. No source fixes, hardware commands or commits were performed for this review.
