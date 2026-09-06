# System context and bounded contexts

```mermaid
flowchart LR
    User[Operator or asset manager]

    subgraph MTOS
        Web[Web application]
        Assets[Asset management]
        Operations[Railroad operation]
        CommandAdapters[Command-station adapters]
        AccessoryAdapter[Accessory-network adapter]
        Broker[Local MQTT broker]
        Store[(SQLite)]

        Web --> Assets
        Web --> Operations
        Assets --> Store
        Assets -->|eligible asset projection| Operations
        Operations --> CommandAdapters
        Operations --> AccessoryAdapter
        AccessoryAdapter --> Broker
    end

    User --> Web
    CommandAdapters --> CommandStation[Command station]
    CommandStation --> Track[Track and locomotives]
    Broker --> Nodes[ESP32 accessory nodes]
    Nodes --> Accessories[Turnouts and signals]
```

## Asset management

Owns durable asset identity, lifecycle, configuration, maintenance,
relationships, and the rules that determine whether an asset may be offered for
operation.

## Railroad operation

Owns live layout operation: control sessions, throttle state, power, occupancy,
routes, interlocking, signals, turnouts, and observed hardware state. It refers
to durable assets by `asset_id` but does not redefine them.

## Command-station adapters

Translate protocol-independent operations into DCC-EX or other hardware
protocols. An adapter owns connection and protocol mechanics, not asset truth.

## Accessory-network adapter

Publishes accessory intent and consumes acknowledgements, reported state, and
node availability. MQTT is the first transport. Retained broker messages and
node-local variables are delivery aids, not MTOS's authoritative state store.

## Optional capabilities

Search, conversational interfaces, and local language models consume public
application operations. They are not authorities and must not bypass domain
validation.
