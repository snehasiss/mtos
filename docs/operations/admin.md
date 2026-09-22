# MTOS administration on Cubietruck

`mtos_admin` is the only MTOS service intended to start with the operating
system. It listens on port 5300 and controls the five-service application stack.
The system unit and every application service run as the dedicated, non-login
`mtos` account. `snehasis` remains the human SSH and system-administration user.

## Prerequisites

Install the host packages as the human administrator:

```bash
sudo apt update
sudo apt install git openssh-client rsync python3 python3-pip python3-full build-essential
```

Create the service identity with its own home but no interactive login shell,
grant serial-device access, and create its project parent:

```bash
sudo useradd --system --create-home --home-dir /home/mtos \
  --shell /usr/sbin/nologin mtos
sudo usermod -aG dialout mtos
sudo install -d -o mtos -g mtos /home/mtos/project
```

If `mtos` already exists, inspect it instead of recreating it:

```bash
getent passwd mtos
id mtos
```

The service account uses Debian's system Python with user-site packages and no
project virtual environment. Create `/home/mtos/.config/pip/pip.conf`, owned by
`mtos:mtos`, with:

```ini
[global]
break-system-packages = true
user = true
```

One safe way to create the parent and empty file before editing is:

```bash
sudo install -d -o mtos -g mtos /home/mtos/.config/pip
sudo install -o mtos -g mtos -m 0644 /dev/null \
  /home/mtos/.config/pip/pip.conf
sudoedit /home/mtos/.config/pip/pip.conf
```

After the reviewed source has been committed and pushed from the development
computer, clone and install it as the service account:

```bash
sudo -u mtos -H git clone \
  https://github.com/snehasiss/mtos.git /home/mtos/project/mtos
cd /home/mtos/project/mtos
sudo -u mtos -H python3 -m pip install --user -r requirements.txt
sudo -u mtos -H python3 -m pip install --user -e .
```

Before installing the service, run the hardware-free suite as that same account:

```bash
cd /home/mtos/project/mtos
sudo -u mtos -H python3 -m pip install --user -e '.[dev]'
sudo -u mtos -H python3 -m pytest -q
```

The checkout, `data/` tree, user-site Python packages and all runtime files must
remain owned by `mtos`. The account receives no sudo privilege and no password.

### Move an existing test installation

If Asset Manager was already tested from
`/home/snehasis/project/mtos`, stop every old process before moving operational
data. Clone the reviewed source afresh as shown above; do not change ownership of
the development checkout or copy its `.git` directory. Then copy only the live
data into the service-owned installation:

```bash
cd /home/snehasis/project/mtos
tools/mtos_services stop
tools/mtos_asset stop
sudo install -d -o mtos -g mtos /home/mtos/project/mtos/data
sudo rsync -a /home/snehasis/project/mtos/data/ \
  /home/mtos/project/mtos/data/
sudo chown -R mtos:mtos /home/mtos/project/mtos/data
```

Confirm that no process still runs from the old checkout. Retain the old data
unchanged until the new service-owned installation has passed its database and
UI checks.

## Configure the outbound backup connection

The SSH key used by the development iMac to enter the Cubietruck as `snehasis`
does not grant the `mtos` service account access to a backup host. Create a
dedicated outbound key owned by `mtos`:

```bash
sudo -u mtos -H ssh-keygen -t ed25519 \
  -f /home/mtos/.ssh/mtos_backup -C mtos-backup
```

Configure a host alias in `/home/mtos/.ssh/config`; substitute the actual host,
account and address:

```sshconfig
Host mtos-backup
    HostName 192.168.1.97
    User snehasis
    IdentityFile ~/.ssh/mtos_backup
    IdentitiesOnly yes
```

Protect the files and authorize the public key on the backup host:

```bash
sudo chown -R mtos:mtos /home/mtos/.ssh
sudo chmod 700 /home/mtos/.ssh
sudo chmod 600 /home/mtos/.ssh/config /home/mtos/.ssh/mtos_backup
sudo chmod 644 /home/mtos/.ssh/mtos_backup.pub
sudo -u mtos -H ssh-copy-id \
  -i /home/mtos/.ssh/mtos_backup.pub mtos-backup
```

Install `rsync` on the backup host, create the intended remote directory, and
accept its host key during this manual setup. Finally verify that future login
cannot prompt for a password:

```bash
sudo -u mtos -H ssh mtos-backup 'mkdir -p /Users/snehasis/project/backup-cubietruck-mtos-data'
sudo -u mtos -H ssh -o BatchMode=yes mtos-backup true
```

Set the fixed remote destination in `/etc/mtos/admin.env` (see below). The
administration page displays it but does not accept a destination from the
browser. For this Cubietruck and iMac, use:

```text
snehasis@mtos-backup:/Users/snehasis/project/backup-cubietruck-mtos-data
```

MTOS synchronizes the complete project `data/` directory to the configured
destination's `data/` subdirectory. The operation uses `--delete`, so
that remote directory is an exact mirror. Do not point it at a directory that
contains unrelated files. Configure snapshots on the backup host if historical
versions are required.

## Install the system service

Generate three different long values:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Run that command three times. Create `/etc/mtos/admin.env` with those distinct,
installation-specific values and the actual project path:

```ini
MTOS_ADMIN_TOKEN=replace-with-a-long-login-token
MTOS_ADMIN_SECRET=replace-with-a-separate-random-session-secret
MTOS_INTERNAL_TOKEN=replace-with-a-third-random-internal-token
MTOS_DATA_DIR=/home/mtos/project/mtos/data
MTOS_BACKUP_REMOTE=snehasis@mtos-backup:/Users/snehasis/project/backup-cubietruck-mtos-data
```

`MTOS_ADMIN_TOKEN` is entered in the browser. `MTOS_ADMIN_SECRET` signs the
browser session. `MTOS_INTERNAL_TOKEN` is inherited by the five application
services and authenticates their private service-to-service requests.

Do not add this file to the repository. Protect it:

```bash
sudo install -d -m 0755 /etc/mtos
sudoedit /etc/mtos/admin.env
sudo chown root:root /etc/mtos/admin.env
sudo chmod 600 /etc/mtos/admin.env
```

From the repository root, instantiate the supplied unit template without
changing the checked-in template:

```bash
cd /home/mtos/project/mtos
sed \
  -e "s|MTOS_PROJECT_ROOT|$PWD|g" \
  deploy/systemd/mtos-admin.service | \
  sudo tee /etc/systemd/system/mtos-admin.service >/dev/null
```

Enable only the Admin service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mtos-admin.service
sudo systemctl status mtos-admin.service
curl http://127.0.0.1:5300/health
```

Open `http://CUBIETRUCK_IP:5300/` from the trusted LAN and enter the configured
admin token.

Inspect live service logs with:

```bash
journalctl -u mtos-admin.service -f
```

## Operating rules

- Start, restart and stop always apply to the complete application stack.
- Stop the stack before backup, restore, or application update. The server also
  enforces this condition.
- Restore first validates the downloaded SQLite databases. On success, the old
  local data remains beside `data/` as `data.before-restore-<UTC timestamp>`.
- Application update is refused if the Cubietruck checkout has local changes.
  The administration page shows the checkout's `origin` repository; updates
  always fetch and check out `main`, then fast-forward from `origin/main`.
  No commit is created.
- The systemd unit restarts `mtos_admin` after a process failure; it does not
  start the other MTOS services.

For local diagnostics, the same admin process can be controlled manually with
`tools/mtos_admin start|stop|restart|status`, provided the Admin token, session
secret and internal token environment variables are present. Run such diagnostics
as `mtos`, not as the human administrator. Normal Cubietruck operation should
use systemd.
