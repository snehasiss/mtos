# MTOS administration on Cubietruck

`mtos_admin` is the only MTOS service intended to start with the operating
system. It listens on port 5300 and controls the five-service application stack.

## Prerequisites

After the reviewed source has been committed and pushed from the development
computer, update the Cubietruck checkout and install its runtime tools and
Python packages. This installation uses Debian's system Python and no project
virtual environment:

```bash
sudo apt update
sudo apt install git openssh-client rsync python3 python3-pip python3-full build-essential
cd ~/project/mtos
git pull --ff-only
python3 -m pip install --user -r requirements.txt
python3 -m pip install --user -e .
```

Before installing the service, run the hardware-free suite on the ARMv7 host:

```bash
python3 -m pip install --user -e '.[dev]'
python3 -m pytest -q
```

## Configure the outbound backup connection

The SSH key used by the development iMac to enter the Cubietruck does not grant
the Cubietruck access to a backup host. Create a dedicated outbound key as the
normal MTOS operating user:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/mtos_backup -C mtos-backup
```

Configure a host alias in `~/.ssh/config`; substitute the actual host, account
and address:

```sshconfig
Host mtos-backup
    HostName 192.168.0.100
    User backup
    IdentityFile ~/.ssh/mtos_backup
    IdentitiesOnly yes
```

Protect the files and authorize the public key on the backup host:

```bash
chmod 700 ~/.ssh
chmod 600 ~/.ssh/config ~/.ssh/mtos_backup
chmod 644 ~/.ssh/mtos_backup.pub
ssh-copy-id -i ~/.ssh/mtos_backup.pub mtos-backup
```

Install `rsync` on the backup host, create the intended remote directory, and
accept its host key during this manual setup. Finally verify that future login
cannot prompt for a password:

```bash
ssh mtos-backup 'mkdir -p /srv/backups/mtos'
ssh -o BatchMode=yes mtos-backup true
```

The UI accepts an absolute remote destination such as:

```text
backup@mtos-backup:/srv/backups/mtos
```

MTOS synchronizes the complete project `data/` directory to
`backup@mtos-backup:/srv/backups/mtos/data/`. The operation uses `--delete`, so
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
MTOS_DATA_DIR=/home/snehasis/project/mtos/data
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
cd ~/project/mtos
sed \
  -e "s|MTOS_USER|$USER|g" \
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
  It fetches and checks out the requested branch or tag but never commits.
- The systemd unit restarts `mtos_admin` after a process failure; it does not
  start the other MTOS services.

For local diagnostics, the same admin process can be controlled manually with
`tools/mtos_admin start|stop|restart|status`, provided the Admin token, session
secret and internal token environment variables are present. Normal Cubietruck
operation should use systemd.
