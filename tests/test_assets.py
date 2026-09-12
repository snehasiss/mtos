from datetime import date

import pytest

from mtos.assets import (
    Asset, AssetFamily, AssetId, AssetLibrary, Component, Connection, Consist,
    ConsistId, Control, Decoder, Lifecycle, Media, Model, Possession, Prototype,
    Relation, Status,
)


def received(asset_id: str, status: Status = Status.STORED,
             location: str | None = None, revision: int = 1) -> Lifecycle:
    return Lifecycle(
        AssetId(asset_id), Possession.RECEIVED, status, location,
        received_on=date(2026, 1, 12), revision=revision,
    )


def test_minimal_asset_has_normalized_classification() -> None:
    asset = Asset(AssetId("C001"), AssetFamily.FREIGHT, "gondola")
    library = AssetLibrary([asset])
    assert library.list(family=AssetFamily.FREIGHT) == (asset,)
    assert asset.to_dict()["family"] == "freight"
    assert asset.to_dict()["type"] == "gondola"
    assert "label" not in asset.to_dict()
    assert "components" not in asset.to_dict()


@pytest.mark.parametrize("signal_type", ["ground_2a", "mainline_3a", "branchline_2a"])
def test_v1_signal_types(signal_type: str) -> None:
    assert Asset(AssetId("G001"), AssetFamily.SIGNAL, signal_type).type == signal_type


def test_updated_roster_vocabulary() -> None:
    Asset(AssetId("C001"), AssetFamily.PASSENGER, "power_car")
    Asset(AssetId("C002"), AssetFamily.PASSENGER, "luggage")
    Asset(AssetId("C003"), AssetFamily.PASSENGER, "brakevan")
    Asset(AssetId("C004"), AssetFamily.FREIGHT, "intermodal")
    Asset(AssetId("C005"), AssetFamily.FREIGHT, "reefer")
    Asset(AssetId("E001"), AssetFamily.MACHINE, "water_tank")
    with pytest.raises(ValueError, match="unsupported"):
        Asset(AssetId("C006"), AssetFamily.PASSENGER, "generator_car")


def test_grouped_asset_payload_is_compact_and_searchable() -> None:
    asset = Asset(
        AssetId("L001"), AssetFamily.LOCO, "diesel",
        model=Model(scale="ho", maker="broadway_limited", product_number="1234"),
        prototype=Prototype(
            maker="emd", model="f7a", reporting_mark="SAL", road_number="4202",
            attributes={"unit": "a", "cab": True},
        ),
        control=Control(
            dcc=True, decoder=Decoder(maker="esu", model="lokpilot_5"),
            address=4202, speed_steps=128,
        ),
    )
    payload = asset.to_dict()
    assert payload["prototype"]["reporting_mark"] == "SAL"
    assert payload["prototype"]["road_number"] == "4202"
    assert payload["model"]["product_number"] == "1234"
    assert payload["control"]["address"] == 4202
    assert "node_id" not in payload["control"]
    assert "lifecycle" not in payload


def test_lifecycle_is_a_separate_record_keyed_by_asset_id() -> None:
    asset = Asset(AssetId("L001"), AssetFamily.LOCO, "diesel")
    lifecycle = received("L001", Status.ACTIVE, "block25")
    library = AssetLibrary([asset], [lifecycle])
    assert library.get_lifecycle("L001") == lifecycle
    assert lifecycle.to_dict()["asset_id"] == "L001"


@pytest.mark.parametrize("possession", [
    Possession.PLANNED, Possession.ORDERED, Possession.SHIPPED,
    Possession.PARKED, Possession.MISSED,
])
def test_unreceived_asset_has_no_inventory_status(possession: Possession) -> None:
    assert Lifecycle(AssetId("L001"), possession=possession).status is None


def test_only_received_assets_can_have_status() -> None:
    with pytest.raises(ValueError, match="only a received"):
        Lifecycle(AssetId("L001"), Possession.SHIPPED, Status.STORED)
    with pytest.raises(ValueError, match="requires a status"):
        Lifecycle(AssetId("L001"), Possession.RECEIVED)


def test_active_rolling_stock_requires_block_location() -> None:
    asset = Asset(AssetId("L001"), AssetFamily.LOCO, "diesel")
    with pytest.raises(ValueError, match="block"):
        AssetLibrary([asset], [received("L001", Status.ACTIVE, "yard_1")])


def test_retirement_is_status_not_possession() -> None:
    asset = Asset(AssetId("C001"), AssetFamily.FREIGHT, "reefer")
    library = AssetLibrary([asset], [received("C001")])
    retired = library.retire("C001", on=date(2026, 9, 13))
    assert retired.possession is Possession.RECEIVED
    assert retired.status is Status.RETIRED
    assert library.list() == ()
    assert library.list(include_retired=True) == (asset,)


def test_turnout_wiring_is_held_once_in_components() -> None:
    turnout = Asset(
        AssetId("T012"), AssetFamily.TURNOUT, "left", label="West yard entrance",
        control=Control(node_id=AssetId("N001")),
        components=(Component(
            "actuator", "servo", "sg90", connection=Connection("servo", 3),
            values={"normal": 310, "reverse": 470},
        ),),
    )
    payload = turnout.to_dict()
    assert payload["control"] == {"node_id": "N001"}
    assert payload["components"][0]["connection"] == {"bus": "servo", "channel": 3}
    assert "outputs" not in payload["control"]


def test_signal_components_use_aspect_refs() -> None:
    signal = Asset(
        AssetId("G013"), AssetFamily.SIGNAL, "mainline_3a",
        control=Control(node_id=AssetId("N002")),
        components=tuple(
            Component(aspect, "led", color, connection=Connection("signal", channel),
                      spec={"resistor_ohm": 680})
            for channel, (aspect, color) in enumerate(
                (("stop", "red"), ("slow", "yellow"), ("go", "green"))
            )
        ),
    )
    assert [item["ref"] for item in signal.to_dict()["components"]] == ["stop", "slow", "go"]


def test_component_refs_are_unique_within_asset() -> None:
    led = Component("stop", "led", "red")
    with pytest.raises(ValueError, match="unique"):
        Asset(AssetId("G001"), AssetFamily.SIGNAL, "ground_2a", components=(led, led))


def test_booster_dependency_and_ordered_consist_are_distinct() -> None:
    cab = Asset(AssetId("L001"), AssetFamily.LOCO, "diesel")
    booster = Asset(
        AssetId("L002"), AssetFamily.LOCO, "booster",
        relations=(Relation("requires", AssetId("L001"), "cab"),),
    )
    consist = Consist(ConsistId("K001"), (cab.id, booster.id))
    library = AssetLibrary(
        [cab, booster],
        [received("L001", Status.ACTIVE, "block25"),
         received("L002", Status.ACTIVE, "block25")],
        [consist],
    )
    assert booster.relations[0].reason == "cab"
    assert library.get_consist("K001").to_dict()["units"] == ["L001", "L002"]


def test_active_dependency_must_be_active_in_same_block() -> None:
    cab = Asset(AssetId("L001"), AssetFamily.LOCO, "diesel")
    booster = Asset(
        AssetId("L002"), AssetFamily.LOCO, "booster",
        relations=(Relation("requires", cab.id, "cab"),),
    )
    library = AssetLibrary([cab, booster], [received("L001", Status.ACTIVE, "block24")])
    with pytest.raises(ValueError, match="block25"):
        library.set_lifecycle(received("L002", Status.ACTIVE, "block25"))


def test_consist_rejects_stationary_assets_and_duplicates() -> None:
    signal = Asset(AssetId("G001"), AssetFamily.SIGNAL, "ground_2a")
    library = AssetLibrary([signal])
    with pytest.raises(ValueError, match="not rolling stock"):
        library.add_consist(Consist(ConsistId("K001"), (signal.id,)))
    with pytest.raises(ValueError, match="twice"):
        Consist(ConsistId("K002"), (signal.id, signal.id))


def test_media_can_be_added_and_primary_image_replaced() -> None:
    asset = Asset(AssetId("C001"), AssetFamily.FREIGHT, "gondola")
    library = AssetLibrary([asset])
    library.add_media("C001", Media(1, "image", "side", "one.jpg", primary=True))
    updated = library.add_media("C001", Media(2, "image", "front", "two.jpg", primary=True))
    assert [item.primary for item in updated.media] == [False, True]
