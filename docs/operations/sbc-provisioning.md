# SBC provisioning for MTOS

This guide reconstructs the completed Cubietruck provisioning and turns it into
a repeatable procedure for a fresh MTOS control host. It covers the operating
system, headless access, networking, Python runtime and hardware permissions.
Application administration begins afterward in [the Admin guide](admin.md).

The guide deliberately corrects unsafe or obsolete suggestions that appeared
during the interactive setup. In particular, it does not perform an in-place
upgrade of the legacy installation, remove Debian's `EXTERNALLY-MANAGED` marker,
run `sudo pip`, disable SSH passwords before key login is proven, or enable five
independent MTOS services at boot.

## Resulting installation

The completed installation has this baseline:

| Item | Selected configuration |
| --- | --- |
| Board | Cubietruck / Allwinner A20, ARMv7, 2 GB RAM |
| Storage | microSD only; no SATA drive |
| OS | Armbian Debian 13 Minimal, headless |
| Verified release | Debian 13.7 |
| Verified kernel | `6.18.52-current-sunxi`, ARMv7 |
| Human administrator | `snehasis`, non-root; SSH public-key login from the development iMac |
| Application account | `mtos`, non-login service identity and application owner |
| Python | Debian system Python 3.13 with user-site packages; no project venv |
| Serial access | Operating account belongs to `dialout` |
| Network | Cubietruck joins the home Wi-Fi using DHCP |
| Stable address | Router-side DHCP reservation is preferred |
| EX-CSB1 | Direct USB serial connection to the Cubietruck |
| ESP32 nodes | Home Wi-Fi; later communicate with MTOS through MQTT |

This installation intentionally gives its sole administrative account
passwordless sudo. That is a site-specific decision for a private home network,
not a general MTOS requirement. Compromise of that account or its private SSH
key is effectively root compromise.

The completed sequence, in brief, was:

1. prepare the boot card on the iMac;
2. move the 32 GB card to the powered-off Cubietruck;
3. connect Cubietruck Ethernet to the home router and power on;
4. discover its DHCP address in the router console;
5. enter the first-boot environment over SSH, set the root password, and create
   the normal user and password;
6. authorize the iMac's SSH public key for passwordless inbound login;
7. update and configure the host and Wi-Fi;
8. create the `mtos` service identity, grant its serial permission, clone MTOS
   under its ownership, and install its Python requirements; and
9. start Asset Manager and verify it from a browser.

## 1. Preserve the legacy installation

The original card ran Linaro 14.01 / Ubuntu 13.10 with a vendor 3.4.79 kernel.
Do not attempt to cross-upgrade it to current Debian. Preserve that card intact
as a physical fallback and install the new OS on another microSD card.

No files were required from the old installation: application source came from
GitHub and new operational data was created or restored separately.

## 2. Select and download the operating system

Use the current Armbian **Debian Minimal** image for Cubietruck. The alternative
Ubuntu XFCE image was rejected because this host is headless and the desktop
environment would consume storage, memory and background CPU without providing
an operational benefit.

Record the image filename and verify its published checksum before writing it.
Do not infer the compression type: an `.img.xz` file requires XZ decompression.

## 3. Write the microSD card from macOS

These commands are destructive. Re-identify the target on every run; never copy
the historical `/dev/disk5` value blindly.

```bash
diskutil list
diskutil unmountDisk /dev/diskN
```

Use macOS's raw device (`rdiskN`) for the actual write. On the development iMac,
the built-in `gzip -dc` successfully decompressed the `.img.xz` stream. The
reusable command is:

```bash
diskutil unmountDisk /dev/diskN
gzip -dc armbian_26.11.0_trixie_cubietruck.img.xz | \
  sudo dd of=/dev/rdiskN bs=1m status=progress
```

For the completed installation, `diskutil list` identified the card as
`/dev/disk5`, so the command actually executed was:

```bash
diskutil unmountDisk /dev/disk5
gzip -dc armbian_26.11.0_trixie_cubietruck.img.xz | \
  sudo dd of=/dev/rdisk5 bs=1m status=progress
```

The required output syntax is `of=/dev/rdisk5`; `of/dev/rdisk5` would be a typo.
The earlier `bs=4M` recollection was not the executed command—macOS used
lowercase `bs=1m`. If a different macOS version does not accept
`status=progress`, press `Ctrl-T` to request a progress report instead. When the
command has completed:

```bash
sync
diskutil eject /dev/diskN
```

Insert the new card in the powered-off Cubietruck and boot it from the 5 V barrel
input. Keep the old card safely labelled and offline.

## 4. Complete first boot

Move the prepared 32 GB microSD card from the iMac to the powered-off
Cubietruck. Connect its Ethernet interface to the home router, then power it on.
The first connection used wired DHCP: its address was found in the router
console and the board was reached over SSH, without a serial console.

For this installation the router assigned `192.168.1.17`. The old OS had left a
stale fingerprint for that address on the iMac. After confirming that replacing
the OS explained the key change, the old entry was removed on the iMac:

```bash
ssh-keygen -f ~/.ssh/known_hosts -R 192.168.1.17
ssh root@192.168.1.17
```

For a later installation, substitute the address shown by the router; do not
assume it will again be `192.168.1.17`. Compare the new fingerprint through a
trusted channel before accepting it.

Complete Armbian's first-boot procedure:

1. replace the initial root password;
2. create the normal `snehasis` account and password;
3. confirm that the account has sudo access;
4. select the locale, timezone and shell;
5. log out of root and perform subsequent work as `snehasis`.

Do not keep routine root SSH access enabled.

## 5. Establish SSH key access

The passwordless key direction configured during provisioning was **iMac to
Cubietruck**. Generate or select a protected Ed25519 key on the development iMac
and authorize its public half for the normal account:

```bash
# Run on the iMac if a suitable key does not already exist.
ssh-keygen -t ed25519 -C "imac-to-cubietruck"
ssh-copy-id snehasis@192.168.1.17
ssh snehasis@192.168.1.17
```

The first `ssh-copy-id` invocation legitimately asks for the newly created
user's password. Subsequent iMac-to-Cubietruck logins use the key. This inbound
key is unrelated to the later **Cubietruck-to-backup-host** key described in the
Admin guide; the latter must be provisioned separately.

Verify key login in a second terminal before changing SSH policy. Then configure
the Cubietruck to reject direct root login. Password authentication may also be
disabled when key recovery has been planned and verified:

```text
PermitRootLogin no
PasswordAuthentication no
```

Place the settings in an appropriate file under `/etc/ssh/sshd_config.d/`, check
the effective configuration, and reload SSH without closing the proven session:

```bash
sudo sshd -t
sudo systemctl reload ssh
```

## 6. Apply the installation-specific sudo policy

For this private installation only, create a validated drop-in instead of
editing `/etc/sudoers` directly:

```bash
sudo visudo -f /etc/sudoers.d/90-mtos-admin
```

Its single rule is:

```sudoers
snehasis ALL=(ALL:ALL) NOPASSWD: ALL
```

Set the standard permissions and test without relying on a cached credential:

```bash
sudo chmod 0440 /etc/sudoers.d/90-mtos-admin
sudo visudo -cf /etc/sudoers.d/90-mtos-admin
sudo -k
sudo -n true
```

`sudo -n true` must succeed without prompting. Do not deploy this unrestricted
rule on a public, shared or multi-user host.

## 7. Update the base operating system

On the fresh maintained image, bring the package set current and reboot if the
kernel or foundational libraries changed:

```bash
sudo apt update
sudo apt full-upgrade -y
sudo reboot
```

Reconnect and record the actual baseline:

```bash
uname -a
cat /etc/debian_version
python3 --version
```

Install the command-line tools used by this installation:

```bash
sudo apt install -y \
  vim git rsync openssh-client \
  python3 python3-pip python3-full python3-dev \
  build-essential
```

Installing Vim provided the expected `vi` alternative automatically. Use
`sudo update-alternatives --config editor` only if the system editor still needs
to be changed.

## 8. Create the MTOS service identity

`snehasis` remains the only human login and performs host administration with
sudo. The application does not run under that account. Create a dedicated
system account with a home directory for its checkout, Python user site and
outbound backup key, but no interactive shell or password:

```bash
sudo useradd --system --create-home --home-dir /home/mtos \
  --shell /usr/sbin/nologin mtos
sudo usermod -aG dialout mtos
sudo install -d -o mtos -g mtos /home/mtos/project
getent passwd mtos
id mtos
```

The expected account owns the application and data, can open EX-CSB1 serial
devices through `dialout`, and runs `mtos_admin`. Admin then starts the five
application services as its own unprivileged `mtos` process. Do not grant this
account sudo or an SSH login password.

## 9. Configure Python without a project virtual environment

MTOS intentionally uses Debian's Python and packages installed into the `mtos`
account's user-site directory. Keep Debian's PEP 668 marker in place and never
use `sudo pip`.

Create `/home/mtos/.config/pip/pip.conf`, owned by `mtos:mtos`:

```ini
[global]
break-system-packages = true
user = true
```

```bash
sudo install -d -o mtos -g mtos /home/mtos/.config/pip
sudo install -o mtos -g mtos -m 0644 /dev/null \
  /home/mtos/.config/pip/pip.conf
sudoedit /home/mtos/.config/pip/pip.conf
```

This is an explicit installation policy: pip may install packages in
`/home/mtos/.local/lib/python3.13/site-packages`, but it must not overwrite
Debian-owned files under `/usr`.

## 10. Install MTOS and its dependencies

Clone the source as the application owner:

```bash
sudo -u mtos -H git clone \
  https://github.com/snehasiss/mtos.git /home/mtos/project/mtos
cd /home/mtos/project/mtos
```

Install the checked-in dependency set and the local package without sudo:

```bash
sudo -u mtos -H python3 -m pip install --user -r requirements.txt
sudo -u mtos -H python3 -m pip install --user -e .
```

Install the development extra only when this host will run the repository test
suite:

```bash
sudo -u mtos -H python3 -m pip install --user -e '.[dev]'
```

On ARMv7, Pillow may need to compile because PyPI does not always provide a
matching wheel. The completed installation built Pillow 12.3.0 successfully
after the development toolchain and image-library headers were available. If a
fresh build fails, install the headers and retry:

```bash
sudo apt install -y \
  libjpeg-dev zlib1g-dev libtiff-dev libfreetype6-dev \
  liblcms2-dev libopenjp2-7-dev libwebp-dev
sudo -u mtos -H python3 -m pip install --user -r requirements.txt
```

Prefer the versions constrained by `requirements.txt`; the historical package
version list is evidence of that installation, not a second dependency manifest.

## 11. Verify serial-device access

The EX-CSB1 is connected by USB and controlled through PySerial. The service
account was added to `dialout` when it was created. Verify that membership:

```bash
id mtos
```

`dialout` must be present. Restart a running system service after changing group
membership. Do not run DCC services as root merely to gain serial access.

## 12. Join the home Wi-Fi

The Cubietruck does **not** operate as an access point. It, the iMac and ESP32
nodes join the existing home network. DHCP remains enabled; a stable address is
assigned by a router-side MAC reservation rather than a static address embedded
in the SBC configuration.

The minimal image did not initially include `nmcli`, so NetworkManager was
installed:

```bash
sudo apt install -y network-manager
sudo systemctl enable --now NetworkManager
```

Before changing network managers on a future image, inspect its existing
networking stack and avoid letting two managers configure the same interface.
For this completed installation, connect interactively so the Wi-Fi password is
not stored in shell history:

```bash
sudo nmtui
```

Select **Activate a connection**, choose the home SSID and supply its password.
Then verify addressing and routing with modern `iproute2` commands:

```bash
ip addr show wlan0
ip link
ip route
```

The legacy `ifconfig` utility is unnecessary. In the router, reserve an address
for the `wlan0` MAC reported by:

```bash
ip link show wlan0
```

Keep Wi-Fi credentials out of the repository and documentation.

## 13. Validate the provisioned host

Run these checks before treating the SBC as ready for MTOS commissioning:

```bash
uname -a
cat /etc/debian_version
python3 --version
sudo -u mtos -H python3 -m pip check
id mtos
ip addr
ip route
sudo -u mtos -H git -C /home/mtos/project/mtos status --short
sudo -u mtos -H python3 -m pytest -q /home/mtos/project/mtos/tests
```

Also verify:

- SSH key login works from the iMac;
- direct root login is disabled;
- `sudo -n true` behaves according to this installation's chosen policy;
- `dialout` is active in a new session;
- the Cubietruck reconnects to home Wi-Fi after reboot;
- the router reservation returns the expected address;
- EX-CSB1 appears under `/dev/serial/by-id/` after USB connection;
- the old microSD card remains intact and labelled.

The completed installation was smoke-tested by starting the Asset service:

```bash
cd /home/mtos/project/mtos
sudo -u mtos -H tools/mtos_asset start
sudo -u mtos -H tools/mtos_asset status
```

Asset Manager was then opened from another device on the trusted LAN at:

```text
http://CUBIETRUCK_IP:5301/
```

After the check, it could be stopped with
`sudo -u mtos -H tools/mtos_asset stop`. This smoke
test demonstrated application startup, the user-installed Python dependencies,
SQLite initialization, LAN binding and browser access. It did not by itself
commission EX-CSB1, DCC, CV programming, MQTT or ESP32 control.

## 14. Apply MTOS-specific administration

Host provisioning does not enable all MTOS services at boot. The current design
uses one authenticated `mtos_admin` system service on port 5300; it starts and
stops the five application services in their safe dependency order. Continue
with [MTOS administration on Cubietruck](admin.md) for:

- Admin, internal-service and session secrets;
- the `mtos-admin.service` systemd unit;
- remote `data/` backup through rsync over SSH;
- application startup, shutdown, restore and update.

The earlier proposal for five independent user-level systemd units and linger is
superseded. Do not install those units.

## Reprovisioning record

For each rebuilt SBC, record the following outside credential files:

```text
provisioned_on:
board:
storage:
image_filename:
image_checksum:
debian_version:
kernel:
python_version:
hostname:
ethernet_mac:
wifi_mac:
reserved_ip:
mtos_revision:
test_result:
```

Never record passwords, Wi-Fi keys, private SSH keys, Admin tokens or internal
service tokens in Git.
