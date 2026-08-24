# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Data model for the `assets` config namespace."""

import logging
import tomllib
from dataclasses import field
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Self, Type

import marshmallow
from frequenz.client.assets import MarketParticipationType
from marshmallow import Schema
from marshmallow_dataclass import dataclass

from ._microgrid import MicrogridConfig
from ._topology import DeliveryAreaConfig, MarketLocationConfig, RelationConfig

_logger = logging.getLogger(__name__)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge two raw config tables, with `override` winning.

    Nested tables are merged recursively; any other value in `override` replaces
    the one in `base`. Merging the raw tables, before they are loaded, keeps a
    field left unset in an override from resetting the base value to its default.

    A `None` override is skipped so the base value survives. TOML has no null, so
    this only matters for a dumped-object layer (e.g. the Assets API) where unset
    fields carry `None`; on real file tables it is a no-op.
    """
    result = dict(base)
    for key, value in override.items():
        if value is None:
            continue
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _merge_file_tables(
    config_files: str | Path | list[str | Path],
) -> dict[str, Any]:
    """Read and deep-merge the raw `assets` tables of one or more files.

    Later files win, entry by entry. Paths that are not files are skipped with a
    warning. Merging before loading lets an override leave a field unset without
    resetting the base value.

    Args:
        config_files: A path or list of paths to TOML config files.

    Returns:
        The merged raw `assets` table, unvalidated.

    Raises:
        ValueError: If no config files are given.
    """
    if isinstance(config_files, (str, Path)):
        paths = [Path(config_files)]
    else:
        paths = [Path(f) for f in config_files]
    if not paths:
        raise ValueError("No config files provided. Please provide at least one.")

    merged: dict[str, Any] = {}
    for config_path in paths:
        if not config_path.is_file():
            _logger.warning("Config path %s is not a file, skipping.", config_path)
            continue
        # pylint: disable-next=protected-access
        merged = _deep_merge(merged, AssetsConfig._read_assets_table(config_path))
    return merged


@dataclass
class AssetsConfig:
    """Entities described by a config document, keyed by their ID."""

    microgrids: dict[int, MicrogridConfig] = field(default_factory=dict)
    """Microgrids, keyed by microgrid ID."""

    market_locations: dict[str, MarketLocationConfig] = field(default_factory=dict)
    """Market locations, keyed by their identifier."""

    relations: dict[str, RelationConfig] = field(default_factory=dict)
    """Market topology relations, keyed by the composite of the sides they connect."""

    class Meta:
        """Ignore entity tables this version does not know about.

        A reader must keep working against files that already carry entities
        added after it, so unknown tables are skipped rather than rejected.
        `_warn_unknown_entities` reports them, so a mistyped table is still
        visible instead of silently loading as empty.
        """

        unknown = marshmallow.EXCLUDE

    Schema: ClassVar[Type[Schema]] = Schema

    def __post_init__(self) -> None:
        """Check that every microgrid is filed under its own ID.

        Relations are not checked here: an override names only the fields it
        changes, so a single document may hold an incomplete record. `check`
        looks at the merged result.

        Raises:
            ValueError: If a key is not the ID of the entry it holds.
        """
        for mid, cfg in self.microgrids.items():
            if int(cfg.meta.microgrid_id) != mid:
                raise ValueError(
                    f"Microgrid ID mismatch: key {mid} != {cfg.meta.microgrid_id}"
                )

    def check(self) -> None:
        """Check the document as a whole, once every layer has been merged.

        Raises:
            ValueError: If an entry's identifier disagrees with the key it is
                filed under, a relation names fewer than two sides, its key
                disagrees with its fields, a gridpool relation names no delivery
                area, one market location is placed in two of them, or a legacy
                microgrid gridpool ID disagrees with its relations.
        """
        for key, location in self.market_locations.items():
            if location.id is None:
                raise ValueError(f"Market location {key}: must name its id")
            if location.id != key:
                raise ValueError(
                    f"Market location key mismatch: key {key} != {location.id}"
                )
        self._check_relations()
        self._check_legacy_gridpool_ids()

    def _check_relations(self) -> None:
        """Check the relations are complete, well-keyed and area-consistent.

        Raises:
            ValueError: If a relation names fewer than two sides, its key
                disagrees with its fields, a gridpool relation names no delivery
                area, one market location is placed in two of them, or one
                delivery-area code appears with two code types.
        """
        for key, relation in self.relations.items():
            if not relation.is_complete:
                raise ValueError(
                    f"Relation {key}: must name at least two of gridpool, microgrid "
                    "and market location"
                )
            if key != relation.key:
                raise ValueError(
                    f"Relation key mismatch: key {key} != {relation.key}, derived "
                    "from the sides the record names"
                )
            if relation.gridpool_id is not None and relation.delivery_area is None:
                raise ValueError(
                    f"Relation {key}: a gridpool relation must name a delivery area"
                )

        zones: dict[str, DeliveryAreaConfig] = {}
        for relation in self.relations.values():
            mlid, zone = relation.market_location_id, relation.delivery_area
            if mlid is None or zone is None:
                continue
            if zones.setdefault(mlid, zone) != zone:
                raise ValueError(
                    f"Market location {mlid} is placed in two delivery areas: "
                    f"{zones[mlid].code} and {zone.code}"
                )

        seen: dict[str, DeliveryAreaConfig] = {}
        for relation in self.relations.values():
            area = relation.delivery_area
            if area is None or area.code is None:
                continue
            if seen.setdefault(area.code, area).code_type != area.code_type:
                raise ValueError(
                    f"Delivery area code {area.code} appears with two code types: "
                    f"{seen[area.code].code_type.name} and {area.code_type.name}"
                )

    def _check_legacy_gridpool_ids(self) -> None:
        """Check legacy microgrid gridpool IDs against the relations."""
        gridpools_by_microgrid: dict[int, set[int]] = {}
        for relation in self.relations.values():
            if relation.microgrid_id is None or relation.gridpool_id is None:
                continue
            gridpools_by_microgrid.setdefault(relation.microgrid_id, set()).add(
                relation.gridpool_id
            )

        for microgrid in self.microgrids.values():
            legacy_gid = microgrid.meta.gid
            if legacy_gid is None:
                continue
            relation_gids = gridpools_by_microgrid.get(microgrid.meta.microgrid_id)
            if relation_gids and relation_gids != {legacy_gid}:
                raise ValueError(
                    f"Microgrid {microgrid.meta.microgrid_id}: legacy meta.gid "
                    f"{legacy_gid} disagrees with relation gridpools "
                    f"{sorted(relation_gids)}; remove meta.gid when several apply"
                )

    def find_relations(
        self,
        *,
        gridpool_id: int | None = None,
        microgrid_id: int | None = None,
        market_location_id: str | None = None,
        delivery_area: str | DeliveryAreaConfig | None = None,
        participation: MarketParticipationType | None = None,
        at: datetime | None = None,
    ) -> list[RelationConfig]:
        """Find the relations naming all of the given sides.

        Args:
            gridpool_id: Gridpool to match, or `None` to ignore.
            microgrid_id: Microgrid to match, or `None` to ignore.
            market_location_id: Market location to match, or `None` to ignore.
            delivery_area: Delivery area to match, a `DeliveryAreaConfig` matched
                on code and code type or a bare code string; `None` to ignore.
            participation: Use case the relation must serve, or `None` to ignore.
            at: Instant the relations, or the given participation, must apply at,
                or `None` to ignore.

        Returns:
            The matching relations, in document order.
        """
        return [
            relation
            for relation in self.relations.values()
            if relation.matches(
                gridpool_id=gridpool_id,
                microgrid_id=microgrid_id,
                market_location_id=market_location_id,
                delivery_area=delivery_area,
                participation=participation,
                at=at,
            )
        ]

    def find_delivery_areas(
        self,
        *,
        gridpool_id: int | None = None,
        microgrid_id: int | None = None,
        market_location_id: str | None = None,
        at: datetime | None = None,
    ) -> list[DeliveryAreaConfig]:
        """List the delivery areas of the matching relations.

        Args:
            gridpool_id: Gridpool to match, or `None` to ignore.
            microgrid_id: Microgrid to match, or `None` to ignore.
            market_location_id: Market location to match, or `None` to ignore.
            at: Instant the relations must apply at, or `None` to ignore.

        Returns:
            The delivery areas, each with its code and code type, deduplicated,
            in document order.
        """
        return list(
            dict.fromkeys(
                relation.delivery_area
                for relation in self.find_relations(
                    gridpool_id=gridpool_id,
                    microgrid_id=microgrid_id,
                    market_location_id=market_location_id,
                    at=at,
                )
                if relation.delivery_area is not None
            )
        )

    def find_market_locations(
        self,
        *,
        gridpool_id: int | None = None,
        microgrid_id: int | None = None,
        delivery_area: str | DeliveryAreaConfig | None = None,
        at: datetime | None = None,
    ) -> list[str]:
        """List the market locations of the matching relations.

        Args:
            gridpool_id: Gridpool to match, or `None` to ignore.
            microgrid_id: Microgrid to match, or `None` to ignore.
            delivery_area: Delivery area to match, a `DeliveryAreaConfig` matched
                on code and code type or a bare code string; `None` to ignore.
            at: Instant the relations must apply at, or `None` to ignore.

        Returns:
            The market locations, deduplicated, in document order.
        """
        return list(
            dict.fromkeys(
                relation.market_location_id
                for relation in self.find_relations(
                    gridpool_id=gridpool_id,
                    microgrid_id=microgrid_id,
                    delivery_area=delivery_area,
                    at=at,
                )
                if relation.market_location_id is not None
            )
        )

    def find_microgrids(
        self,
        *,
        gridpool_id: int | None = None,
        market_location_id: str | None = None,
        delivery_area: str | DeliveryAreaConfig | None = None,
        at: datetime | None = None,
    ) -> list[int]:
        """List the microgrids of the matching relations.

        Args:
            gridpool_id: Gridpool to match, or `None` to ignore.
            market_location_id: Market location to match, or `None` to ignore.
            delivery_area: Delivery area to match, a `DeliveryAreaConfig` matched
                on code and code type or a bare code string; `None` to ignore.
            at: Instant the relations must apply at, or `None` to ignore.

        Returns:
            The microgrids, deduplicated, in document order.
        """
        return list(
            dict.fromkeys(
                relation.microgrid_id
                for relation in self.find_relations(
                    gridpool_id=gridpool_id,
                    market_location_id=market_location_id,
                    delivery_area=delivery_area,
                    at=at,
                )
                if relation.microgrid_id is not None
            )
        )

    @classmethod
    def _warn_unknown_entities(cls, assets: dict[str, Any], source: Path) -> None:
        """Warn about entity tables that this version drops on load."""
        if unknown := sorted(set(assets) - set(cls.Schema().fields)):
            _logger.warning(
                "%s: ignoring unknown entity tables under `assets`: %s",
                source,
                ", ".join(unknown),
            )

    @classmethod
    def _read_assets_table(cls, config_path: Path) -> dict[str, Any]:
        """Read the raw `assets` table from a TOML file.

        Entries live under `assets`. A document without an `assets` table is
        read in the deprecated layout, where the microgrid entries sit at the
        top level.

        Args:
            config_path: The path to the TOML configuration file.

        Returns:
            The raw `assets` table, unvalidated, for merging before it is loaded.

        Raises:
            TypeError: If `assets` is not a table.
            ValueError: If both layouts are present, which means a half-migrated
                file rather than a merge.
        """
        with config_path.open("rb") as f:
            data: dict[str, Any] = tomllib.load(f)

        if "assets" not in data:
            _logger.warning(
                "%s: top-level microgrid IDs are deprecated, "
                "nest the entries under `assets.microgrids` instead.",
                config_path,
            )
            data = {"assets": {"microgrids": data}}

        assets = data["assets"]
        if not isinstance(assets, dict):
            raise TypeError(
                f"{config_path}: `assets` must be a table, got {type(assets)}"
            )

        if unprefixed := sorted(k for k in data if k != "assets"):
            raise ValueError(
                f"{config_path}: keys {unprefixed} sit outside `assets` while the "
                "file already has an `assets` table; move them under "
                "`assets.microgrids`."
            )

        cls._warn_unknown_entities(assets, config_path)
        return assets

    @classmethod
    def load_from_files(
        cls,
        config_files: str | Path | list[str | Path],
        check: bool = True,
    ) -> Self:
        """Load and validate a config document from one or more TOML files.

        Later files take precedence, entry by entry, so a file can override
        single fields of an entry another defines. The raw tables are merged
        before they are loaded, so a field left unset in an override keeps the
        base value rather than being reset to its default. Paths that are not
        files are skipped with a warning.

        Args:
            config_files: A path or list of paths to TOML config files.
            check: Whether to run the whole-document `check`. It skips only that
                cross-entity pass; the schema and each entry's own validation
                still run. Pass all layers of a stack together rather than
                loading one incomplete override with `check=False`.

        Returns:
            The merged document.
        """
        merged = _merge_file_tables(config_files)
        loaded = cls.Schema().load(merged)
        assert isinstance(loaded, cls)
        if check:
            loaded.check()
        return loaded
