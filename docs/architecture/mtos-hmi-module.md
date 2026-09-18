# mtos_hmi module checkpoint

Date: 2026-09-18. Status: integrated for Phase 1 DCC MAIN operation.

`mtos_hmi` is the browser-facing human-machine interface on `0.0.0.0:5302`.
It serves the compiled React/TypeScript interface and owns browser sessions,
not railroad state or hardware.

Socket.IO replaces one-second HTTP polling. A browser receives an initial full
snapshot and server-pushed snapshots/events. Commands carry `command_id`,
monotonic `client_seq`, operation and payload. The acknowledgement means only
that HMI accepted the command; completion or failure arrives as a separate event.
Hardware work executes outside the Socket.IO request handler.

Version 1 boundaries are enforced:

- at most eight browser sessions;
- at most 32 outstanding commands per browser;
- 16 KiB command and 64 KiB Socket.IO transport limit;
- 1,024-event in-memory replay boundary;
- increasing client sequence per session;
- same-origin browser connection and loopback Core client.

HMI calls only the Core gateway. It does not import a roster repository, open
serial hardware or publish MQTT. `tools/mtos_hmi` is the canonical launcher;
`tools/asset_control` is now a compatibility alias for the same service and PID.

The React UI retains the accepted iPhone-first throttle/function presentation.
Its API adapter now uses `socket.io-client`; no one-second status timer remains.
The production bundle is rebuilt under `src/mtos/control_ui`.

Core now supplies the HMI snapshot, active-locomotive roster, serial-device list
and typed command gateway. HMI pushes changed Core/device state to connected
browsers. The same HMI service will later present CV and microcontroller-backed
turnout, signal and machine controls, but those screens and `mtos_mc` do not yet
exist; current operational coverage is DCC MAIN only.
