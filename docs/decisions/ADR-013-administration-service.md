# ADR-013: Dedicated administration service and remote data continuity

- Status: Accepted
- Date: 2026-09-22

## Context

MTOS runs continuously on a Cubietruck, but its five application services do
not need to start merely because the computer has booted. The operator needs a
small, dependable interface for inspecting and controlling those services from
an iPhone, backing up all operational data to another computer, restoring it,
and updating the deployed checkout. This administrative path must remain
available while the application stack is stopped.

`data/` is intentionally outside Git and contains all databases, photographs,
runtime state and other installation data. A backup to another directory on the
same computer does not protect against storage or host failure.

## Decision

`mtos_admin` is a separate Flask service on LAN port 5300. It is the only MTOS
service enabled at operating-system startup and is managed by systemd. It and
the application services run as the dedicated non-login `mtos` account, which
owns the checkout, data and serial-device access. The human `snehasis` account
retains SSH and sudo responsibility but does not own application processes. The
operator explicitly starts and stops the application stack from its mobile-first
web interface. The stack remains the existing five services:

- `mtos_asset`
- `mtos_dcc`
- `mtos_mc`
- `mtos_core`
- `mtos_hmi`

Service operations use the existing `tools/mtos_services` coordinator, preserving
its dependency-aware startup and reverse-order shutdown behavior.

Backup and restore use `rsync` over SSH with non-interactive public-key
authentication. The destination must have the form
`user@host:/absolute/path`; local destinations and password prompts are rejected.
The complete local `data/` tree is synchronized to `<remote>/data/` with
deletions, making that directory an exact remote mirror. The remote host key and
SSH key authorization must be configured manually before using the UI.

Backup, restore and Git update require all five application services to be
stopped. Restore downloads into a staging directory, checks every SQLite
database with `PRAGMA integrity_check`, requires an Asset database, obtains the
exclusive data-directory lock, and only then swaps the restored tree into place.
The previous local tree is retained as a timestamped sibling for recovery.

Application update accepts a branch or tag, refuses a dirty checkout, fetches
from `origin`, checks out the requested ref, and fast-forwards a branch. It never
creates a commit.

The LAN-facing administrator authenticates with an installation-specific token.
Its session cookie is HTTP-only and SameSite Strict, and state-changing requests
require a session CSRF token. Administrative jobs are serialized so two service,
data or checkout mutations cannot overlap.

## Consequences

- Port 5300 remains available when the application stack is stopped.
- MTOS application services do not need individual systemd units or boot-time
  enablement.
- The Cubietruck must have `git`, `openssh-client` and `rsync` installed.
- The remote account and destination need suitable filesystem permissions.
- The remote `data/` directory is a current mirror, not a history of snapshots.
  Snapshot history, if wanted, belongs on the remote filesystem or backup host.
- Restoring replaces the complete data tree, so the UI requires deliberate
  confirmation and the previous local tree is preserved.
- The admin token and Flask session secret are installation configuration and
  must never be committed to Git.
