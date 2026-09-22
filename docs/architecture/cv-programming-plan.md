# CV programming design and implementation plan

Date: 2026-09-21. Status: software implementation checkpoint; no hardware commissioning yet.

## Objective and boundary

Add service-mode decoder programming to the existing MTOS DCC/Core/HMI stack,
using a permanently wired, isolated programming track. This increment covers:

- reading the decoder address;
- writing and verifying the decoder address;
- reading one CV;
- writing one CV followed by readback;
- durable outcomes and reconciliation where physical and Asset state can diverge.

A bounded test run on the programming-track rails remains designed but disabled
until JOIN/DriveAway has been commissioned against the installed EX-CSB1.

A primary use case is recovering a locomotive whose decoder address was not
recorded correctly and which responds to neither address 3 nor its road number.
Address read must therefore work without knowing or trusting the Asset record's
current `control.address`.

Programming on Main (PoM), decoder-definition files, full decoder sheets, bulk
read/write, automatic decoder identification and JMRI DecoderPro parity are not
Version 1 scope. PoM is especially excluded from address changes.

Cubietruck porting and device commissioning are a parallel workstream. They may
prove the serial transport, but must not expand the CV feature silently.

## Fixed physical arrangement

The two tracks always remain electrically isolated from each other on both rails:

| EX-CSB1 output | MTOS location | Normal role |
|---|---|---|
| A | `test_main_1` | MAIN operation and ordinary test running |
| B | `test_prog_1` | PROG service-mode programming |

They are never connected together through track, jumpers or a common selector.
The software must verify TrackManager reports A as MAIN and B as PROG before a
programming session. A mismatch is an error; MTOS must not guess from terminal
labels. Only one locomotive/decoder may be on `test_prog_1` during service-mode
programming because those commands are not decoder-address selective.

Version 1 also requires MAIN power to be confirmed off for the whole programming
transaction. The isolated wiring could permit programming while A is operating,
but the conservative rule removes another uncontrolled state during initial
commissioning. Relaxing it later requires a separate reviewed decision.

## Can `test_prog_1` also be a test-running track?

Yes, subject to supervised verification. DCC-EX documents two possible methods:

1. **JOIN/DriveAway (preferred experiment).** `<1 JOIN>` sends the MAIN DCC
   waveform to the PROG output; `<0 JOIN>` returns it from that state. DCC-EX
   describes this specifically for testing or driving a locomotive away after
   programming. A later programming command automatically protects itself by
   returning to programming behavior.
2. **TrackManager role switching (fallback).** Change B from PROG to MAIN, query
   and verify it, run the test, power off, restore B to PROG, and verify again.
   TrackManager turns power off when modes change and permits only one PROG
   output. This path changes the configured role and therefore needs more
   recovery logic.

JOIN is the proposed Version 1 route because it expresses the intended temporary
test directly and avoids treating B as a general MAIN district. It is not yet an
accepted hardware fact. Commissioning must confirm the installed EX-CSB1 firmware,
the exact JOIN responses, scoped power behavior and safe return to B=PROG. If JOIN
cannot be observed and controlled deterministically, use explicit B mode switching
instead. Do not implement both paths in the first UI.

During a joined test, MAIN packets reach both A and B. Initially require the
operator to confirm `test_main_1` is clear and the programming locomotive is the
only powered decoder. Without occupancy and identity detection MTOS cannot prove
that physically. Test mode starts at speed zero, permits a low configurable speed
ceiling, never restores an old throttle, and ends with stop, power off, UNJOIN and
verified B=PROG. Emergency stop remains available throughout.

## Correct DCC-EX command contract

The existing generic commands are useful but address programming needs correction
before physical use:

| Operation | Native command | Expected meaning |
|---|---|---|
| read decoder address | `<R>` | DCC-EX resolves the effective locomotive ID |
| write decoder address | `<W address>` | DCC-EX updates all required address/consist CVs |
| read CV | `<R cv callback sub>` | correlated service-mode CV read |
| write CV | `<W cv value>` | service-mode CV write response |
| query outputs | `<=>` | reports TrackManager state for A/B |

The current backend manually writes CV1/CV17/CV18/CV29. It passed fake tests but
must not be commissioned: DCC-EX advises using its address command because reading
CV1 alone does not identify the effective address and an address change can involve
up to six CVs, including consist state. Replace that implementation with `<R>` and
`<W address>`, then confirm the address with another `<R>`.

Generic CV write remains followed by readback. Do not automatically retry any
write after timeout: the physical write may have succeeded even when its response
was lost. Negative decoder/ACK responses are failures with their native diagnostic
code retained as evidence.

## Ownership and transaction model

- **Asset** owns `control.address`, lifecycle and decoder-related master data.
- **DCC** exclusively owns serial framing, programming requests, output/JOIN state
  and physical readback.
- **Core** owns the durable programming session, eligibility, lease/fencing,
  reconciliation and conditional Asset update.
- **HMI** collects operator intent and shows evidence; it owns no railroad state.

Address workflow:

```text
operator confirmation
  -> Core durable pending operation and lease
  -> DCC verifies A MAIN / B PROG and MAIN off
  -> DCC reads current decoder address
  -> DCC writes the new address with <W address>
  -> DCC reads address again
  -> Core conditionally updates Asset control.address
  -> completed / confirmed
```

Address read is a separate diagnostic workflow. It sends `<R>` on the isolated
PROG track and reports the effective decoder address without changing the decoder
or Asset. Service-mode address read does not use the recorded DCC address. The
operator can select the physically known Asset before or after the read and compare
**Recorded address** with **Decoder address**. If the physical locomotive cannot
yet be identified, the read result may remain an unassigned session observation;
it must not be attached to an Asset by inference alone.

If the decoder may have changed but verification or the Asset update fails, the
operation is `uncertain`. Store requested address, address observed before/after,
Asset revision, command-station evidence and error. Block another address change
for that asset until supervised reconciliation; never claim rollback.

Generic CV values are transactional evidence, not automatically Asset fields.
Only explicitly modelled facts (such as decoder address) update Asset. A later
decoder-profile design can decide which named CV settings belong in master data.

## Eligibility and session states

Every programming-track session requires:

- EX-CSB1 ready with A=MAIN and B=PROG;
- MAIN power confirmed off;
- operator confirmation that exactly one decoder is on `test_prog_1`.

**Read Address** may run without selecting an Asset, specifically to recover an
unknown or incorrectly recorded decoder address. If an Asset is selected for
comparison, it must be received, in maintenance and located at `test_prog_1`.

Address write and any Asset-linked programming operation additionally require:

- family `loco`, or a self-propelled `mow` asset;
- `control.dcc == true`;
- possession `received`;
- status `maintenance`;
- location exactly `test_prog_1`;
- current Asset revision leased by Core;
- explicit selection of the physical Asset on the track.

Session states are `idle`, `checking`, `ready`, `reading`, `writing`, `verifying`,
`test_ready`, `test_running`, `closing`, `completed`, `failed` and `uncertain`.
Only one programming session exists at a time. While it is active, ordinary DCC
commands are rejected except emergency stop and the session's bounded test-run
commands.

## HMI design

Enable the existing **Programming** tab only when DCC is ready. Keep it phone-first
and divide it into compact sections:

1. **Programming track** — A/B reported roles, MAIN power, JOIN state and a clear
   ready/not-ready reason.
2. **Decoder on `test_prog_1`** — optionally select the physically known eligible
   maintenance asset; show asset ID, reporting mark/road number, recorded address
   and revision. Asset selection is required for a write, but not for address read.
3. **Safety confirmation** — one locomotive on PROG; initially also confirm MAIN
   track clear. Confirmation expires when device/session/output state changes.
4. **Address** — use a compact commercial-handset pattern with one address display/
   entry and exactly two explicit, full touch-target buttons: **Read Address** and
   **Write Address**. They must not be represented by one mode-dependent button,
   and there is no routine Save button.
   Read Address ignores the entered/recorded address, sends `<R>`, and places the
   returned value in a separate **Decoder address** result while leaving Asset
   untouched. Write Address uses the entered **New address**, requires an Asset,
   confirmation and successful readback, then Core updates Asset within that same
   coordinated operation. The operator is not left with a separate Save step.
   Always show **Recorded address**, **Decoder address**, and **New address** with
   distinct labels so a recovered value is never mistaken for a committed value.
   Present physical/Asset mismatch and uncertain reconciliation explicitly.
5. **CV** — CV number 1–1024, value 0–255, Read and guarded Write; show the most
   recent requested and verified result. Do not expose arbitrary raw serial text.
6. **Test on programming track** — available only after a successful read/write
   and JOIN commissioning; Enter Test Mode, direction, low speed control, Stop and
   End Test. No full operating function keyboard in the first increment.

Every operational section retains a dedicated message area at all times. It reports
the section's current state and most recent result—waiting, checking, reading,
writing, verifying, completed, failed or uncertain—rather than disappearing like
a transient notification. It has no visible “STATUS” caption because its placement
and content already communicate its purpose. Reserve its space to avoid layout
movement, update it through an accessible polite live region, and keep failures
visible until the operator performs another action or explicitly dismisses them.

Writes require a confirmation dialog containing asset, physical location, CV or
address, old observed value when known and requested value. Reads do not require
confirmation. A successful Read Address must never automatically overwrite
`control.address`; offer a subsequent, explicit reconciliation/write choice.
Disable controls while a request is outstanding rather than allowing parallel
touches.

If decoder write/readback succeeds but the Asset commit fails, preserve the
operation as `uncertain` and show a contextual **Reconcile** action with the
physical evidence. Reconcile is an exceptional recovery control, not a permanent
third address button.

## API and code increments

### `mtos_dcc`

- parse the single-value `<r address>` response;
- implement `read_loco_address()` and dedicated `write_loco_address(address)`;
- retain correlated `read_cv()` and verified `write_cv()`;
- model A/B modes, scoped power and JOIN as reported/unknown—not optimistic flags;
- add guarded enter/exit test-mode primitives after commissioning chooses JOIN or
  TrackManager switching;
- one exclusive programming/session lock around the entire sequence.

### `mtos_core`

- require `test_prog_1` in addition to maintenance eligibility;
- add a non-mutating read-address operation that does not require the current
  roster address and can return an unassigned observation;
- add durable read-CV and write-CV operations;
- replace the current manual address-CV orchestration with the dedicated DCC
  address command and conditional Asset commit;
- expose session/test-mode commands to HMI and preserve uncertain evidence;
- invalidate/close the session if Asset revision or device session changes.

### `mtos_hmi`

- add typed Socket.IO commands and completion events for the programming actions;
- implement the compact Programming tab and explicit safety/uncertainty states;
- resynchronize the full programming/session snapshot after reconnect rather than
  assuming a lost acknowledgement means failure.

## Implementation checkpoints

1. **Protocol correction and fake tests:** address read/write commands and parser,
   general CV read/write/readback, negative responses, timeouts and late replies.
2. **Core transaction tests:** eligibility including `test_prog_1`, fencing,
   idempotency, conditional Asset update, uncertain outcomes and reconciliation.
3. **HMI without hardware:** Programming tab, validation, confirmation, disabled
   states, separate Read Address/Write Address controls, recorded-versus-decoder
   mismatch, reconnect/resynchronization and iPhone layout.
4. **Read-only hardware commissioning:** verify firmware, A/B states and repeated
   `<R>`/manufacturer CV reads on one known decoder. Record exact responses.
5. **One reversible write:** read a harmless agreed CV, write a test value, read it
   back, restore the original and read again.
6. **Address commissioning:** only after the previous steps, program one agreed
   address and verify physical plus Asset state/recovery.
7. **PROG-track test run:** commission JOIN first; speed zero, low-speed movement,
   stop, exit, B=PROG verification and restart/no-replay test.

Checkpoints 1–3 are implemented with fake serial/service tests and a built React
UI. The implementation uses dedicated `<R>` and `<W address>` commands, readback,
Core eligibility at `test_prog_1`, conditional Asset address persistence, an
unassigned address-read path, generic CV read/write/readback and persistent HMI
result areas. Checkpoints 4–7 require the physical setup and remain pending.

Do not use UP903999 or another decoder with unresolved motion/sound behavior as
the first programming subject. Choose a known-good, expendable/test locomotive
and record its decoder maker/model and initial CV/address evidence.

## Acceptance and failure scenarios

Automated coverage must include malformed/partial/late replies, negative ACKs,
no decoder, multiple requests, disconnect during read/write, restart after likely
write, stale Asset revision, location/status change during a session, unexpected
A/B mode, MAIN not confirmed off, JOIN failure, lost connection while joined,
emergency stop, and failure to restore B=PROG.

On process or serial failure during test mode, attempt emergency stop and power
off if communication remains available, mark output state unknown, and require
operator inspection. Software feedback is never proof that track power is absent.

## Official references

- [DCC-EX serial programming](https://dcc-ex.com/mkdocs-test/products/ex-commandstation/loco-programming/serial-programming/)
- [DCC-EX TrackManager](https://dcc-ex.com/trackmanager/index.html)
- [EX-CSB1 track connections](https://dcc-ex.com/ex-commandstation/rtr-connecting.html)
- [DCC-EX DriveAway/JOIN](https://dcc-ex.com/throttles/driveaway.html)
- [DCC-EX programming overview](https://dcc-ex.com/reference/software/programming-locos.html)
