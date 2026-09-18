# MTOS design review and memory assessment

Date: 2026-09-18

**Yes—the new MTOS design should fit on a 2 GB Cubietruck A20 for normal operation without local AI inference. An 8 GB Raspberry Pi is not required by this architecture.** If buying new hardware, I would choose a **Raspberry Pi 5 with 4 GB** for CPU performance and headroom.

This is a design-based estimate, not a hardware benchmark: the latest six-service architecture is documented but not yet implemented.

## My assessment of the design

I reviewed the current working-tree context, architecture documents, ADRs, and relevant implementation. The governing direction is [ADR-009](decisions/ADR-009-service-decomposition-and-control-architecture.md), with five normal services and optional `mtos_ai`.

The separation is sound:

- **Asset** owns inventory and configuration.
- **HMI** handles browsers and live updates.
- **Core** authorizes operations, reserves resources, and enforces deterministic rules.
- **DCC** exclusively owns the command station.
- **MC** owns accessory execution and MQTT.
- **AI** proposes intent without gaining hardware authority.

The strongest decisions are keeping AI outside the control path, distinguishing acknowledgement from physical completion, retaining uncertain operations for reconciliation, and running servo timing and flashing locally on ESP32 nodes. Those decisions also keep the SBC workload small.

Socket.IO should improve responsiveness, but **moving hardware waits out of browser request handling is equally important**. WebSockets alone will not fix blocked workers or command queues.

I would keep the accepted process separation. Five small Python services are reasonable here; they do not inherently require several gigabytes.

## The design gaps I would resolve first

1. **Asset edits versus Core reservations need an explicit cross-service protocol.**
   The earlier design relied on a shared SQLite transaction. ADR-009 separates ownership, but a revision check followed by dispatch is insufficient: configuration could change between those steps. Define how Asset atomically protects an operating configuration, how Core obtains that protection, and how it survives restart. This is the most consequential migration issue.

2. **Core failure and emergency behaviour need a concrete contract.**
   DCC has an independent emergency write path, but normally accepts commands only from Core. Specify what happens when Core hangs while trains are running: adapter watchdog behaviour, stale-command rejection, reconnection fencing, and the available emergency mechanism. The documents acknowledge this concern without fully resolving it.

3. **Core and MC need precise ownership of durable jobs.**
   Core owns the operational journal; MC owns durable accessory jobs. That can work, but define their shared command identity and recovery protocol. If MC accepts a job and its response is lost, Core must discover its outcome without causing another physical execution.

4. **“Bounded” needs actual limits.**
   Set queue capacity, per-browser backlog, event size/history, MQTT inflight limits, and journal retention. Slow clients should resynchronize rather than accumulate unlimited events. The current serial event deque is bounded at 256, but the current command journal inserts records without an evident pruning path in its repository.

5. **Bring the older documents into alignment.**
   The [architecture companion](architecture/control-service-architecture.md) still lists whether Core warrants its own process as an open choice, although ADR-009 decides it does. Older contracts retain single-process/shared-database assumptions. These should be explicitly marked superseded so implementation does not mix incompatible guarantees.

These are implementable gaps. They do not undermine the overall direction, but they matter more than adding RAM.

## Estimated normal memory footprint

For sizing, I assumed:

- A headless Linux installation.
- Approximately the documented 159 assets, four ESP32 nodes, 20 turnouts and 20 signals.
- One to four browser clients and a handful of operating locomotives.
- One application worker per service, bounded threads and queues.
- Compiled React assets, with browsers running on phones/computers.
- No local model inference or frontend development server.

The following are **planning allowances, not measured RSS figures**:

| Component | Estimated resident-memory allowance |
|---|---:|
| `mtos_asset`, ordinary browsing/API use | 50–100 MiB |
| `mtos_hmi`, including small WebSocket deployment | 60–120 MiB |
| `mtos_core` | 50–100 MiB |
| `mtos_dcc` | 30–60 MiB |
| `mtos_mc` | 35–70 MiB |
| Mosquitto | 5–20 MiB |
| **Application subtotal** | **230–470 MiB** |
| Headless OS and supporting services | 180–300 MiB |

I would budget **roughly 0.5–0.9 GiB for normal whole-system operation**, excluding additional reclaimable filesystem cache. A 2 GB board should therefore have useful headroom.

SQLite does not require loading the database into RAM. Photos remain files, and React executes in the client browser. The number of Python processes is likely to contribute more baseline memory than the layout’s operational state.

**The main memory spike is photo processing.** The current [image optimizer](../src/mtos/image_optimizer.py) decodes and transforms the original before producing the small output. A 48-megapixel image needs roughly 137–183 MiB for just one 3–4-byte-per-pixel buffer; transformations can retain several buffers. A 20 MB upload limit does not bound decoded memory.

For the Cubietruck, serialize image optimization, impose a decoded-pixel limit, and avoid bulk imports while operating trains. Without those controls, concurrent large uploads could exhaust 2 GB despite low normal usage.

## Cubietruck versus Raspberry Pi

| Hardware | Assessment |
|---|---|
| **Cubietruck A20, 2 GB** | Plausible for the complete non-AI control stack; validate latency and stability on the board |
| **Raspberry Pi, 2 GB** | Adequate memory under these assumptions |
| **Raspberry Pi 5, 4 GB** | My preferred new purchase for this workload |
| **Raspberry Pi 5, 8 GB** | Useful for additional applications or local AI experiments; unnecessary for ordinary MTOS control |

The A20’s disadvantage is its older CPU and platform support, rather than an obvious RAM shortage. Armbian currently lists Cubietruck as **Community** support and offers a minimal CLI image; that establishes an installation option, not proof that your particular board and peripherals will work reliably. [Armbian Cubietruck](https://armbian.com/boards/cubietruck)

A Pi 5 provides a modern quad-core Cortex-A76 CPU and 4 GB/8 GB options. Its extra CPU capacity would help with image processing, reconnect bursts, and concurrent inventory/control activity. [Raspberry Pi specifications](https://www.raspberrypi.com/products/raspberry-pi-5/)

Local AI should have a separate budget. At four bits per parameter, a 3-billion-parameter model already has approximately 1.5 GB of raw weights, before runtime buffers and context cache. **Keeping inference on the Axon preserves the Cubietruck’s viability**, as the design already intends.

Before declaring the A20 supported, run the extracted services with fake hardware through a sustained workload: several browser sessions, normal command traffic, reconnects, and image uploads. Measure proportional process memory, system `MemAvailable`, swap activity, and command/event latency. The acceptance criterion should include responsive emergency handling under load, not merely successful startup.

**I would retain the Cubietruck for the first deployment trial, keep AI remote, and buy a 4 GB Pi 5 only if measured responsiveness or platform reliability justifies it.** ADR-009’s description of the A20 constraint as obsolete is a design choice—not evidence that MTOS has outgrown 2 GB.
