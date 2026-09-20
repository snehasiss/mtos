# mtos_core module checkpoint

Date: 2026-09-20. Status: DCC MAIN and address-programming orchestration implemented; MC remains hardware-free.

`mtos_core` is the sole operational authority on `127.0.0.1:5303`. It owns a
separate `data/db/core.sqlite3` journal and reservation projection. It does not
own asset master data or serial hardware.

For locomotive commands Core:

1. resolves the immutable asset through the Asset client contract;
2. validates family, possession, status and DCC configuration;
3. requests an Asset-owned lease for the expected revision;
4. records the lease/fencing token and accepted command durably;
5. dispatches an address-level command to DCC with Core session and asset fence;
6. records completion or `uncertain` without blindly replaying an unknown action.

Repeated `command_id` with an identical command returns the stored result and
does not execute hardware again. Reuse for another payload is rejected. Emergency
stop latches Core and blocks movement/function commands until explicit resume.
Core establishes DCC and MC sessions and sends two-second heartbeats in a
background thread; readiness becomes false if heartbeat delivery fails.

For stationary assets Core validates family, lifecycle and operation-specific
values, acquires the Asset lease/fence, records the canonical transaction, then
submits a typed execution to MC. MC results are reconciled into the Core journal;
Core remains the operational authority while `mc.sqlite3` remains subordinate
hardware-execution evidence.

The internal API exposes start/readiness/state, heartbeat, MAIN power, throttle,
functions, locomotive stop, emergency stop, resume, stationary-asset lists and
typed turnout/signal/machine commands. It requires the internal token and has no
browser UI.

For `POST /v1/assets/<asset_id>/program-address`, Core requires a received,
maintenance-state, DCC-equipped `loco` or `mow`. It journals the old/new address
and asset revision, acquires the Asset lease, asks DCC to program and verify the
decoder, and only after confirmed readback calls Asset's conditional programmed-
address endpoint. Hardware success followed by an Asset revision/update failure
is recorded as `uncertain` with both addresses and hardware evidence; it is never
reported as a successful rollback or automatically retried.

Run it with:

```bash
tools/mtos_core start
tools/mtos_core status
tools/mtos_core stop
```

The Asset control-lease endpoint and HMI projection are implemented. A durable
Core epoch permits a newly started Core session to supersede its own stale lease
while producing a higher per-asset fence for DCC. The integrated startup tool
establishes both adapter sessions before HMI is exposed as ready. Real EX-CSB1
and ESP32/electronics commissioning has not yet been performed.
