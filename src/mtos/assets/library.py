"""Cross-record rules for the normalized MTOS asset roster."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from typing import Iterable

from .model import (
    Asset, AssetFamily, AssetId, Consist, ConsistId, Lifecycle, Media,
    ROLLING_FAMILIES, Status, is_block,
)


class AssetLibrary:
    """Storage-neutral aggregate enforcing asset, lifecycle and consist rules."""

    def __init__(
        self,
        assets: Iterable[Asset] = (),
        lifecycles: Iterable[Lifecycle] = (),
        consists: Iterable[Consist] = (),
    ) -> None:
        self._assets: dict[AssetId, Asset] = {}
        self._lifecycles: dict[AssetId, Lifecycle] = {}
        self._consists: dict[ConsistId, Consist] = {}
        for asset in assets:
            self.add(asset)
        for lifecycle in lifecycles:
            self.set_lifecycle(lifecycle)
        for consist in consists:
            self.add_consist(consist)

    def add(self, asset: Asset) -> Asset:
        if asset.id in self._assets:
            raise ValueError(f"asset already exists: {asset.id}")
        candidate = {**self._assets, asset.id: asset}
        self._validate_relations(candidate)
        self._assets = candidate
        return asset

    def get(self, asset_id: AssetId | str) -> Asset:
        key = self._asset_id(asset_id)
        try:
            return self._assets[key]
        except KeyError as error:
            raise KeyError(f"asset not found: {key}") from error

    def list(
        self, *, family: AssetFamily | None = None, include_retired: bool = False
    ) -> tuple[Asset, ...]:
        return tuple(
            asset
            for asset in self._assets.values()
            if (family is None or asset.family is family)
            and (
                include_retired
                or self._lifecycles.get(asset.id) is None
                or self._lifecycles[asset.id].status is not Status.RETIRED
            )
        )

    def update(self, asset: Asset) -> Asset:
        previous = self.get(asset.id)
        if asset.created_at != previous.created_at:
            raise ValueError("created_at is immutable")
        updated = replace(asset, updated_at=datetime.now(timezone.utc))
        candidate = {**self._assets, updated.id: updated}
        self._validate_relations(candidate)
        self._validate_active_dependencies(candidate, self._lifecycles)
        self._assets = candidate
        return updated

    def add_media(self, asset_id: AssetId | str, media: Media) -> Asset:
        asset = self.get(asset_id)
        if any(existing.id == media.id for existing in asset.media):
            raise ValueError(f"media already exists for {asset.id}: {media.id}")
        items = tuple(
            replace(existing, primary=False) if media.primary else existing
            for existing in asset.media
        ) + (media,)
        return self.update(replace(asset, media=items))

    def set_lifecycle(self, lifecycle: Lifecycle) -> Lifecycle:
        asset = self.get(lifecycle.asset_id)
        previous = self._lifecycles.get(asset.id)
        if previous is not None and lifecycle.revision <= previous.revision:
            raise ValueError("lifecycle revision must increase")
        candidate = {**self._lifecycles, asset.id: lifecycle}
        self._validate_location(asset, lifecycle)
        self._validate_active_dependencies(self._assets, candidate)
        self._lifecycles = candidate
        return lifecycle

    def get_lifecycle(self, asset_id: AssetId | str) -> Lifecycle:
        key = self._asset_id(asset_id)
        try:
            return self._lifecycles[key]
        except KeyError as error:
            raise KeyError(f"lifecycle not found: {key}") from error

    def retire(self, asset_id: AssetId | str, *, on: date) -> Lifecycle:
        previous = self.get_lifecycle(asset_id)
        return self.set_lifecycle(
            replace(
                previous,
                status=Status.RETIRED,
                retired_on=on,
                revision=previous.revision + 1,
                updated_at=datetime.now(timezone.utc),
            )
        )

    def add_consist(self, consist: Consist) -> Consist:
        if consist.id in self._consists:
            raise ValueError(f"consist already exists: {consist.id}")
        for unit in consist.units:
            asset = self.get(unit)
            if asset.family not in ROLLING_FAMILIES:
                raise ValueError(f"consist unit is not rolling stock: {unit}")
        self._consists[consist.id] = consist
        return consist

    def get_consist(self, consist_id: ConsistId | str) -> Consist:
        key = consist_id if isinstance(consist_id, ConsistId) else ConsistId(consist_id)
        try:
            return self._consists[key]
        except KeyError as error:
            raise KeyError(f"consist not found: {key}") from error

    @staticmethod
    def _validate_location(asset: Asset, lifecycle: Lifecycle) -> None:
        if (
            lifecycle.status is Status.ACTIVE
            and asset.family in ROLLING_FAMILIES
            and not is_block(lifecycle.location)
        ):
            raise ValueError("active rolling stock location must be a block such as block25")

    @staticmethod
    def _validate_relations(assets: dict[AssetId, Asset]) -> None:
        for asset in assets.values():
            for relation in asset.relations:
                if relation.asset_id not in assets:
                    raise ValueError(f"required asset not found: {relation.asset_id}")

    @staticmethod
    def _validate_active_dependencies(
        assets: dict[AssetId, Asset], lifecycles: dict[AssetId, Lifecycle]
    ) -> None:
        for asset in assets.values():
            lifecycle = lifecycles.get(asset.id)
            if lifecycle is None or lifecycle.status is not Status.ACTIVE:
                continue
            requirements = tuple(link for link in asset.relations if link.rel == "requires")
            if asset.family is AssetFamily.LOCO and asset.type == "booster":
                if not any(link.reason == "cab" for link in requirements):
                    raise ValueError("active booster requires a cab locomotive")
            for requirement in requirements:
                target = lifecycles.get(requirement.asset_id)
                if target is None or target.status is not Status.ACTIVE:
                    raise ValueError(f"required asset is not active: {requirement.asset_id}")
                if target.location != lifecycle.location:
                    raise ValueError(
                        f"required asset must be in {lifecycle.location}: {requirement.asset_id}"
                    )

    @staticmethod
    def _asset_id(asset_id: AssetId | str) -> AssetId:
        return asset_id if isinstance(asset_id, AssetId) else AssetId(asset_id)
