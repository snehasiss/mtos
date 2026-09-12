# Initial domain vocabulary

This vocabulary is deliberately small. Terms should be added only with a clear
railroad meaning and an identified owner.

| Term | Initial meaning |
|---|---|
| Asset | One physical item known to MTOS and identified by an immutable `asset_id`. |
| Rolling stock | Assets capable of occupying or moving on track, including locomotives, cars, and maintenance-of-way equipment. |
| Stationary asset | A fixed layout asset such as a turnout, signal, detector, or operating trackside device. |
| Prototype | The real railway subject represented by a model asset. |
| Product | A manufactured model-rail product or catalog definition; not necessarily an owned physical asset. |
| Configuration | Mutable technical settings and installed components used to operate an asset. |
| Lifecycle | Possession and inventory status stored separately from asset master data. |
| Consist | An ordered roster of rolling-stock asset IDs; not a permanent asset relationship. |
| Operational state | Current commanded or observed state of the railroad. |
| Transaction | A durable business or technical workflow with an outcome. |
| Event | An immutable fact that something happened at a recorded time. |
| Operational eligibility | A derived decision that an asset can be offered for a specified operation. |
| Command-station adapter | A protocol boundary translating MTOS operations to specific hardware. |

## Naming rules

- Use railroad-domain terms when they exist; for example, `rolling_stock`
  rather than `movable_asset`.
- Use `asset_id` for relationships between asset-domain records.
- Do not use reporting marks, road numbers, decoder addresses, or filesystem
  names as primary keys.
- Do not place lifecycle location, speed, direction, signal aspect, or turnout
  position in asset master data.
- Avoid generic nullable structures shared by unrelated concrete asset types.
