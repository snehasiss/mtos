# mtos_hmi module checkpoint

Date: 2026-09-18. Status: integrated for DCC MAIN and the hardware-free MC path.

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
- 1,024-event in-memory history boundary; reconnect replay/resynchronization is
  still incomplete;
- increasing client sequence per session;
- same-origin browser connection and loopback Core client.

HMI calls only the Core gateway. It does not import a roster repository, open
serial hardware or publish MQTT. `tools/mtos_hmi` is the canonical launcher;
`tools/asset_control` is now a compatibility alias for the same service and PID.

The React UI retains the accepted iPhone-first throttle/function presentation.
Its API adapter now uses `socket.io-client`; no one-second status timer remains.
The production bundle is rebuilt under `src/mtos/control_ui`.

Core now supplies the HMI snapshot, active-locomotive roster, stationary-asset
roster, device state and typed command gateway. HMI pushes changed Core/device
state to connected browsers. Turnout, signal and machine tabs route typed
commands through Core to `mtos_mc`; they remain disabled unless MQTT is connected
and the selected node reports a compatible, configuration-matched ready state.
This path is covered by fake-transport tests but is not hardware-commissioned.
The coordinated decoder-address programming backend now exists behind Core and
DCC, but HMI still exposes no live Programming workflow. General CV/PROG remains
deferred, and the address path is not hardware-commissioned.
