# mtos_dcc module checkpoint

Date: 2026-09-20. Status: MAIN integrated; guarded address-programming backend implemented but not physically commissioned.

`mtos_dcc` is the EX-CSB1 hardware abstraction on `127.0.0.1:5304`. It owns
serial discovery, exactly one command-station connection, DCC-EX framing/parsing,
observed device state and address-level MAIN commands. It does not import the
roster, decide asset eligibility or accept asset names from a browser.

Core establishes a session with a monotonically increasing epoch and heartbeats
every two seconds. DCC considers it stale after six seconds, rejects normal
commands and attempts one DCC-EX all-stop when the serial station is ready.
Asset operations carry an asset ID and fencing token; lower tokens are rejected.
The normal admission limit is 64 commands. Emergency stop bypasses that limit.

The internal JSON API includes health/readiness/state, serial-device discovery,
connect/disconnect, Core session/heartbeat, MAIN power, throttle, function,
locomotive stop and all-stop. Mutations require `X-MTOS-Internal-Token`.
The service is loopback-only by default and starts disconnected. It sends no
power-on command, but reports physical MAIN power as `unknown` until verified;
software startup cannot claim that externally powered hardware is de-energized.

Run it with:

```bash
tools/mtos_dcc start
tools/mtos_dcc status
tools/mtos_dcc stop
```

Fake-station tests cover session fencing, stale-token rejection, watchdog stop,
authentication and typed command projection. Real EX-CSB1 commissioning remains
supervised and was not performed at this checkpoint.

The Phase 2 backend now also parses CV replies and exposes one bounded
`POST /v1/programming/address` operation. It requires a verified PROG output and
MAIN power off, serializes the whole address transaction, preserves unrelated
CV29 bits, writes the short or long address CVs, and reads every affected CV back.
It does not update Asset; only Core may request the conditional Asset commit.
Timeouts are not retried. The HMI programming screen and real decoder test remain
pending, so this is an implemented/tested software contract rather than hardware
commissioning evidence.
