# ADR-011: Cubietruck operating-system and Python environment

- **Status:** Accepted and executed
- **Date:** 2026-09-20

## Context

The Cubietruck A20 previously ran an obsolete Linaro installation with a 3.4-era
kernel. It could not provide a maintained operating system or the Python and TLS
environment required by MTOS. The board has 2 GB RAM and will run headless, so a
desktop environment would consume resources without helping railroad operation.

The owner does not want a project virtual environment on the deployment host.
MTOS requires Python 3.11 or newer and the packages listed in `requirements.txt`.
The old microSD card is retained as a recoverable fallback while the replacement
installation is validated.

## Decision

1. Install the current Armbian Debian 13 Minimal image for Cubietruck on a new
   microSD card. Do not attempt an in-place upgrade of the old Linaro system.
2. Run the board headlessly. Use the normal non-root `snehasis` account only for
   human SSH and system administration. A dedicated non-login `mtos` system
   account owns the deployed repository, data, Python user site and MTOS
   processes, including `mtos_admin`.
3. Use Debian's system Python, provided it is Python 3.11 or newer. Install MTOS
   runtime dependencies for that interpreter from `requirements.txt`; do not
   create `.venv` on this host.
4. Because Debian marks its Python environment as externally managed, use an
   explicit user-level pip policy only if the required packages are unavailable
   as Debian packages. The chosen user configuration is:

   ```ini
   [global]
   break-system-packages = true
   user = true
   ```

   This installs into the user's site directory. Never run project `pip` commands
   with `sudo`, and never remove Debian's `EXTERNALLY-MANAGED` marker.
5. Install the host tools needed by the current repository:

   ```bash
   sudo apt update
   sudo apt full-upgrade
   sudo apt install git python3 python3-pip python3-full build-essential
   sudo -u mtos -H python3 -m pip install --user -r requirements.txt
   sudo -u mtos -H python3 -m pip install --user -e .
   ```

6. Add the `mtos` service account to `dialout` for EX-CSB1 serial access:

   ```bash
   sudo usermod -aG dialout mtos
   ```

7. MTOS and its service account do not require root execution or passwordless
   sudo. Installations should
   follow their normal host-security policy and grant only the administrative
   privileges appropriate to their environment.

## Custom configuration for this installation

The owner's Cubietruck is a headless appliance on a private home network. For
operational convenience, this specific installation permits passwordless sudo
for its sole administrative account:

```sudoers
snehasis ALL=(ALL:ALL) NOPASSWD: ALL
```

Direct root login is disabled, and administrative login from the development
iMac uses SSH public-key authentication. The rule must be added with `visudo` or
a validated file under `/etc/sudoers.d/`; sudoers must never be edited without
syntax validation.

The accepted installation-specific tradeoff is that compromise of the `snehasis`
account or its SSH private key is effectively equivalent to root compromise. The
iMac private key must therefore remain protected, password authentication should
remain disabled after key access is verified, and SSH must not be exposed
directly to the public Internet. If the host later moves outside this trust
boundary or gains additional users, replace unrestricted `NOPASSWD` with a
command-scoped rule or ordinary authenticated sudo.

## Installation record

The new card was prepared and Armbian Debian 13 Minimal was installed. The MTOS
repository was cloned and the Python environment was configured. Application and
hardware testing are recorded separately by ADR-012; this ADR does not claim that
the EX-CSB1, MQTT, ESP32 nodes or the five-service stack have been commissioned.
The owner-specific legacy background and evidence checklist are preserved in
[the Cubietruck installation context](../operations/cubietruck-installation-context.md).

The completed macOS imaging command used `gzip -dc` successfully for the
`.img.xz` stream and wrote `/dev/rdisk5` with `bs=1m`; the reproducible command
and its destructive-device safeguards are recorded in the SBC provisioning
guide. Always re-identify the target disk and verify the image checksum.

## Consequences

- The board receives current security and Python support with low idle overhead.
- Runtime packages live in the unprivileged `mtos` account's Python site rather
  than `.venv`.
- In this installation, routine remote administration does not pause for a sudo
  password, while root SSH login remains disabled and sudo activity remains
  attributable to the named account in system logs.
- For this installation, possession of the account's SSH key provides a path to
  unrestricted root, so key protection and the private-network boundary are
  security requirements. This is not a general MTOS deployment requirement.
- A future Debian/Python upgrade may require reinstalling compatible packages.
- The old microSD remains the rollback mechanism until commissioning succeeds.
