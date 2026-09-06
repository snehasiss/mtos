# MTOS

**Model Train Operating System**

MTOS is a lightweight, open-source platform for managing model-rail assets and
operating a model railway. It is intended to run on modest single-board
computers and provide a browser-based experience without requiring JMRI,
WiThrottle, or another heavyweight desktop application.

## Project intent

MTOS will provide one coherent platform for:

- asset inventory, acquisition, configuration, maintenance, and retirement;
- layout definition, including track, turnouts, signals, and trackside assets;
- command-station integration and safe train control;
- programming locomotives and accessories;
- operating sessions, routes, interlocking, and eventual automation;
- phone, tablet, and desktop access through a lightweight web interface.

MTOS is not tied to a railroad, scale, command station, control protocol, or
host computer. Hardware and protocol integrations are adapters around the MTOS
domain rather than assumptions embedded in it.

## Status

MTOS is at the architecture and domain-model stage. The earlier
`union-pacific-layout` repository is a reference implementation and migration
source, not the foundation of this codebase.

Current design material is under [`docs/`](docs/README.md).

## License and name

Source code is licensed under the Apache License 2.0. See [`LICENSE`](LICENSE).

MTOS, Model Train Operating System, and future MTOS logos identify the official
project and are not licensed as product names for modified distributions. See
[`TRADEMARKS.md`](TRADEMARKS.md).

