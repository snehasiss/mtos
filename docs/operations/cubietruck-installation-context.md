# Cubietruck installation context

Date recorded: 2026-09-20. Scope: owner-specific deployment history.

This document preserves the migration background for the Cubietruck used by the
project owner. It is not a requirement for other MTOS installations. General
architecture remains hardware-independent; ADR-011 records the resulting local
operating-system and Python decisions, and ADR-012 governs MTOS deployment and
commissioning on this host.

## Hardware and legacy state

- **Board:** Cubietruck, Allwinner A20, dual-core ARMv7 Cortex-A7, 2 GB RAM.
- **Original distribution:** Linaro 14.01 based on Ubuntu 13.10 “Saucy
  Salamander”, which has been end-of-life since 2014.
- **Observed original kernel:** `Linux cubietruck 3.4.79 #1 SMP PREEMPT`.
- **Original storage:** 32 GB microSD card.

The old card is retained intact as a bare-metal fallback while the replacement
installation is tested. It is not a current security-supported runtime and should
not be reconnected as the normal networked control host.

## Why a clean installation was selected

An in-place distribution upgrade was rejected as unacceptably risky. The legacy
installation spans end-of-life repositories, an old vendor/BSP kernel and former
Allwinner boot configuration such as FEX/`script.bin`. Attempting to cross that
gap could leave the board unbootable without producing a trustworthy modern
system. A clean installation on a second card also preserves a physical rollback
path.

The decision is about repeatability and risk, not a claim that every theoretical
upgrade path is technically impossible. Likewise, availability of modern Python
packages must be verified on ARMv7; packages without compatible wheels may build
from source or require Debian packages.

## Replacement installation

- **Distribution:** Armbian Debian 13 “Trixie” Minimal.
- **Role:** Headless MTOS control host on the owner's private LAN.
- **Storage:** Separate microSD card; no SATA storage is currently planned.
- **Python:** System Python 3.11 or newer, with user-site packages and no project
  `.venv`, as described by ADR-011.
- **Application:** MTOS checked out from GitHub; software and hardware
  commissioning follows ADR-012.

The intended kernel baseline is the maintained mainline-family kernel shipped by
the selected Armbian image. The installed version should be recorded from
`uname -a`; this document does not infer an exact version merely from the image
name.

## Installation-specific security boundary

The owner connects from the development iMac using SSH public-key authentication.
Direct root login is disabled. The sole administrative account has the
installation-specific passwordless-sudo configuration recorded in ADR-011. This
is not general MTOS setup guidance and depends on the private-network and key
protection assumptions stated there.

## Commissioning evidence still required

Record the following before treating the Cubietruck as the operational host:

- output of `uname -a`, `python3 --version` and `git rev-parse HEAD`;
- successful automated test result on ARMv7;
- five-service startup/status/shutdown result using `tools/mtos_services`;
- available memory, CPU load and microSD behavior during a representative run;
- EX-CSB1 serial discovery, identity feedback and supervised MAIN-track test;
- backup and restore verification for `data/db/` and `data/media/`;
- MQTT/ESP32 commissioning separately, when that hardware is available.

Do not put passwords, private keys, Wi-Fi credentials or the internal MTOS token
in this document or in Git.

