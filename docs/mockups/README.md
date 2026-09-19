# Historical MAIN control UI proposal

This mockup predates the React `mtos_hmi` implementation. It remains a visual
design record, not the current operator interface or an executable specification.

Open [asset-control-main.html](asset-control-main.html) in a browser. This is a
standalone interactive mockup with sample identities; it makes no API requests
or device connections. Resize to approximately 393 px for iPhone or 940 px for
desktop. Use the preview-state selector for disconnected, ready/power-off,
running and emergency-stop states.

The visual basis is union-pacific-layout/src/csb1/frontend/src/styles.css and
App.tsx: Inter/system fonts, dark-green panels, amber selections, generous touch
targets and function buttons. Proposed refinements are collapsible connection
details, explicitly labelled MAIN power, an emergency-stop resume action, fine
speed adjustment and responsive desktop columns. All function names stay numeric
until decoder-specific labels are configured. Programming is added in Phase 2.

This was the visual review checkpoint before implementation. Mock state changes
are immediate simulations; production controls must wait for the applicable
device outcome and implement the reviewed command contracts.

Review refinement: the emergency button is a red equilateral triangle with a
white exclamation mark in a 48 px target matching the logo. Operation and disabled
Programming navigation precede locomotive selection. Reverse is left, Forward
right. Function pages have 16 buttons (the final page ends at F68), with separate
previous/next triangle controls. Explanatory text was removed from the operating
panels and preview scenarios moved into collapsed settings. Essential disabled
state and emergency messages remain. Touch controls retain at least 44 px targets.

Location is omitted from the throttle: roster location is manually maintained,
not detected live. Movement cannot update it automatically until an explicit
tracking/detection workflow is implemented. This does not change inventory data.

The latest review makes function keys square while retaining their bevels,
strengthens panel and control borders, and reduces the tab type so the shared
navigation can later include Turnout and Signal. EX-CSB1 is explicitly labelled
as the USB/serial command station. Its connection and MAIN-power panel is specific
to locomotive operation and later CV programming. Phase 3 ESP32 nodes use Wi-Fi
and MQTT and will show accessory-network/node status within the same visual shell,
not CSB1-style USB connect or track-power controls.

The emergency control now uses a heavily rounded triangular outline: red outer
edge, narrow white separation and solid red inner triangle with a white mark.
