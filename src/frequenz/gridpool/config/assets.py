# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Data model for the `assets` config namespace."""

import logging
import tomllib
from dataclasses import field
from datetime import date
from pathlib import Path
from typing import Any, ClassVar, Self, Type, TypeVar

import marshmallow
from marshmallow import Schema
from marshmallow_dataclass import dataclass

from .microgrid import MicrogridConfig, deep_merge, merge_config_maps
from .topology import MarketLocationConfig, RelationConfig

_logger = logging.getLogger(__name__)

_T = TypeVar("_T", MarketLocationConfig, RelationConfig)


@dataclass
class AssetsConfig:
    """Entities described by a config document, keyed by their ID."""

    microgrids: dict[str, MicrogridConfig] = field(default_factory=dict)
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
            if not mid.isdigit():
                raise ValueError(f"Microgrid ID key must be numeric, got {mid}")
            if int(cfg.meta.microgrid_id) != int(mid):
                raise ValueError(
                    f"Microgrid ID mismatch: key {mid} != {cfg.meta.microgrid_id}"
                )

    def check(self) -> None:
        """Check the document as a whole, once every layer has been merged.

        Raises:
            ValueError: If a relation names no enterprise or no asset, if its key
                disagrees with its fields, or if two relations that apply at once
                claim the same asset for different enterprises.
        """
        for key, relation in self.relations.items():
            if not relation.is_complete:
                raise ValueError(
                    f"Relation {key}: must name an enterprise and at least one "
                    "gridpool, microgrid or market location"
                )
            if key != relation.key:
                raise ValueError(
                    f"Relation key mismatch: key {key} != {relation.key}, derived "
                    "from the sides the record names"
                )

        self._check_owners()

    def _check_owners(self) -> None:
        """Check that no asset has two owners at the same time.

        Raises:
            ValueError: If two relations that apply at once name the same asset
                under different enterprises.
        """
        seen: dict[tuple[str, int | str], list[RelationConfig]] = {}
        for relation in self.relations.values():
            for asset in relation.assets.items():
                for other in seen.setdefault(asset, []):
                    if other.enterprise_id != relation.enterprise_id and (
                        relation.overlaps(other)
                    ):
                        raise ValueError(
                            f"Relation {relation.key}: enterprise "
                            f"{relation.enterprise_id} disagrees with "
                            f"{other.enterprise_id} of {other.key}, which owns the "
                            "same asset at the same time"
                        )
                seen[asset].append(relation)

    def market_location(self, market_location: str) -> MarketLocationConfig:
        """Get how to read a market location identifier.

        Args:
            market_location: The identifier, as used in a relation.

        Returns:
            Its entry, or one with the defaults when the document has none, so
            that only locations departing from them have to be listed.
        """
        return self.market_locations.get(market_location, MarketLocationConfig())

    def delivery_area(self, relation: RelationConfig) -> str | None:
        """Get the grid zone a relation applies in.

        Args:
            relation: The relation to look up.

        Returns:
            The zone of its market location, or of its microgrid when it names
            none, or `None` when neither entry says.
        """
        if relation.market_location_id is not None:
            area = self.market_location(relation.market_location_id).delivery_area
            if area is not None:
                return area
        if relation.microgrid_id is not None:
            microgrid = self.microgrids.get(str(relation.microgrid_id))
            if microgrid is not None:
                return microgrid.meta.delivery_area
        return None

    def find_relations(  # pylint: disable=too-many-arguments
        self,
        *,
        enterprise_id: int | None = None,
        gridpool_id: int | None = None,
        microgrid_id: int | None = None,
        market_location_id: str | None = None,
        at: date | None = None,
        ownership: bool | None = False,
    ) -> list[RelationConfig]:
        """Find the relations naming all of the given sides.

        Args:
            enterprise_id: Enterprise to match, or `None` to ignore.
            gridpool_id: Gridpool to match, or `None` to ignore.
            microgrid_id: Microgrid to match, or `None` to ignore.
            market_location_id: Market location to match, or `None` to ignore.
            at: Day the relations must apply on, or `None` to ignore.
            ownership: Whether to return the records that only say who owns a
                single asset. They are left out by default, since a query about
                the topology is rarely about them; `None` returns both kinds.

        Returns:
            The matching relations, in document order.
        """
        return [
            relation
            for relation in self.relations.values()
            if relation.matches(
                enterprise_id=enterprise_id,
                gridpool_id=gridpool_id,
                microgrid_id=microgrid_id,
                market_location_id=market_location_id,
                at=at,
            )
            and (ownership is None or relation.is_ownership == ownership)
        ]

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
    def load_from_file(cls, config_path: Path, check: bool = True) -> Self:
        """Load and validate a config document from a TOML file.

        Entries live under `assets`. A document without an `assets` table is
        read in the deprecated layout, where the microgrid entries sit at the
        top level.

        Args:
            config_path: The path to the TOML configuration file.
            check: Whether to check the document as a whole. Pass `False` for a
                file that is one layer of several, since an override is
                incomplete until it has been merged.

        Returns:
            The loaded configuration.

        Raises:
            TypeError: If `assets` is not a table.
            ValueError: If both layouts are present, which means a
                half-migrated file rather than a merge.
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
        loaded = cls.Schema().load(assets)
        assert isinstance(loaded, cls)
        if check:
            loaded.check()
        return loaded


def _merge_assets_configs(base: AssetsConfig, override: AssetsConfig) -> AssetsConfig:
    """Merge two config documents, with *override* taking precedence.

    Entries present in only one document are kept, entries present in both are
    merged field by field, and a field left unset in *override* keeps the value
    from *base*. The checks of `AssetsConfig` run over the result, so a document
    can carry the relations of a gridpool whose enterprise another one names.

    Args:
        base: The document to merge into.
        override: The document taking precedence.

    Returns:
        A new document representing the merged result.
    """
    return AssetsConfig(
        microgrids=merge_config_maps(base.microgrids, override.microgrids),
        market_locations=_merge_entities(
            base.market_locations, override.market_locations
        ),
        relations=_merge_entities(base.relations, override.relations),
    )


def _merge_entities(base: dict[str, _T], override: dict[str, _T]) -> dict[str, _T]:
    """Merge two tables of the same entity type, with *override* winning.

    Args:
        base: The table to merge into.
        override: The table taking precedence.

    Returns:
        A new table representing the merged result.
    """
    merged = dict(base)
    for key, entry in override.items():
        if key in merged:
            schema = type(entry).Schema()
            loaded = schema.load(
                deep_merge(schema.dump(merged[key]), schema.dump(entry))
            )
            assert isinstance(loaded, type(entry))
            merged[key] = loaded
        else:
            merged[key] = entry
    return merged
