# MTOS administration on Cubietruck

`mtos_admin` is the only MTOS service intended to start with the operating
system. It listens on port 5300 and controls the five-service application stack.

## Prerequisites

Install the runtime tools on the Cubietruck:

```bash
sudo apt install git openssh-client rsync
```

Create an SSH key for the MTOS operating user, authorize it on the backup host,
and accept the remote host key once. Verify that login cannot prompt for a
password:

```bash
ssh -o BatchMode=yes backup@backup-host true
```

The UI accepts an absolute remote destination such as:

```text
backup@backup-host:/srv/backups/mtos
```

MTOS synchronizes the complete project `data/` directory to
`backup@backup-host:/srv/backups/mtos/data/`. The operation uses `--delete`, so
that remote directory is an exact mirror. Do not point it at a directory that
contains unrelated files. Configure snapshots on the backup host if historical
versions are required.

## Install the system service

Create `/etc/mtos/admin.env` with long, installation-specific secrets:

```bash
MTOS_ADMIN_TOKEN=replace-with-a-long-login-token
MTOS_ADMIN_SECRET=replace-with-a-separate-random-session-secret
MTOS_DATA_DIR=/home/mtos/project/mtos/data
```

Do not add this file to the repository. Copy
`deploy/systemd/mtos-admin.service` to `/etc/systemd/system/mtos-admin.service`
and replace `MTOS_USER` and `MTOS_PROJECT_ROOT` with the Cubietruck user and
absolute checkout path. Then enable only the admin service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mtos-admin.service
sudo systemctl status mtos-admin.service
```

Open `http://CUBIETRUCK_IP:5300/` from the trusted LAN and enter the configured
admin token.

## Operating rules

- Start, restart and stop always apply to the complete application stack.
- Stop the stack before backup, restore, or application update. The server also
  enforces this condition.
- Restore first validates the downloaded SQLite databases. On success, the old
  local data remains beside `data/` as `data.before-restore-<UTC timestamp>`.
- Application update is refused if the Cubietruck checkout has local changes.
  It fetches and checks out the requested branch or tag but never commits.
- The systemd unit restarts `mtos_admin` after a process failure; it does not
  start the other MTOS services.

For local diagnostics, the same admin process can be controlled manually with
`tools/mtos_admin start|stop|restart|status`, provided the two secret environment
variables are present. Normal Cubietruck operation should use systemd.

