# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Data model for the `assets` config namespace."""

import logging
import tomllib
from dataclasses import field
from datetime import date
from pathlib import Path
from typing import Any, ClassVar, Self, Type

import marshmallow
from marshmallow import Schema
from marshmallow_dataclass import dataclass

from .microgrid import MicrogridConfig
from .topology import MarketLocationConfig

_logger = logging.getLogger(__name__)


@dataclass
class AssetsConfig:
    """Entities described by a config document, keyed by their ID."""

    microgrids: dict[str, MicrogridConfig] = field(default_factory=dict)
    """Microgrids, keyed by microgrid ID."""

    market_locations: dict[str, MarketLocationConfig] = field(default_factory=dict)
    """Market locations, keyed by their identifier."""

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
        """Check that each entry is filed under its own ID.

        Raises:
            ValueError: If a key is not a numeric microgrid ID, or does not
                match its entry's `meta.microgrid_id`.
        """
        for mid, cfg in self.microgrids.items():
            if not mid.isdigit():
                raise ValueError(f"Microgrid ID key must be numeric, got {mid}")
            if int(cfg.meta.microgrid_id) != int(mid):
                raise ValueError(
                    f"Microgrid ID mismatch: key {mid} != {cfg.meta.microgrid_id}"
                )

    def market_location(self, market_location_id: str) -> MarketLocationConfig:
        """Get how to read a market location identifier.

        Args:
            market_location_id: The identifier, as used elsewhere.

        Returns:
            Its entry, or one with the defaults when the document has none.
        """
        return self.market_locations.get(market_location_id, MarketLocationConfig())

    def market_locations_of(
        self, microgrid_id: int, at: date | None = None
    ) -> list[str]:
        """Find the market locations metering a microgrid.

        Args:
            microgrid_id: The microgrid to look up.
            at: Day to read the links on, or `None` for the latest.

        Returns:
            Their identifiers, in document order.
        """
        return [
            key
            for key, location in self.market_locations.items()
            if location.microgrid(at) == microgrid_id
        ]

    def gridpool_of(self, microgrid_id: int, at: date | None = None) -> int | None:
        """Find the gridpool a microgrid takes part in.

        The link sits on the market locations metering the microgrid, and on the
        microgrid itself when none does, so both have to be consulted.

        Args:
            microgrid_id: The microgrid to look up.
            at: Day to read the links on, or `None` for the latest.

        Returns:
            The gridpool ID, or `None` when nothing names one.

        Raises:
            ValueError: If the market locations of the microgrid name different
                gridpools, which no single value can answer.
        """
        found = {
            self.market_location(key).gridpool(at)
            for key in self.market_locations_of(microgrid_id, at)
        } - {None}
        if len(found) > 1:
            raise ValueError(
                f"Microgrid {microgrid_id}: its market locations name gridpools "
                f"{sorted(str(gid) for gid in found)}"
            )
        if found:
            return found.pop()
        microgrid = self.microgrids.get(str(microgrid_id))
        return microgrid.meta.gridpool(at) if microgrid else None

    def delivery_area_of(self, microgrid_id: int, at: date | None = None) -> str | None:
        """Find the grid zone a microgrid sits in.

        Args:
            microgrid_id: The microgrid to look up.
            at: Day to read the links on, or `None` for the latest.

        Returns:
            The zone, from a market location metering it, or from the microgrid
            itself when none does.
        """
        for key in self.market_locations_of(microgrid_id, at):
            area = self.market_location(key).delivery_area
            if area is not None:
                return area
        microgrid = self.microgrids.get(str(microgrid_id))
        return microgrid.meta.delivery_area if microgrid else None

    def enterprise_of(self, microgrid_id: int, at: date | None = None) -> int | None:
        """Find the enterprise a microgrid belongs to.

        Args:
            microgrid_id: The microgrid to look up.
            at: Day to read the links on, or `None` for the latest.

        Returns:
            The enterprise ID, from the microgrid itself or from a market
            location metering it.
        """
        microgrid = self.microgrids.get(str(microgrid_id))
        if microgrid is not None:
            owner = microgrid.meta.enterprise(at)
            if owner is not None:
                return owner
        for key in self.market_locations_of(microgrid_id, at):
            owner = self.market_location(key).enterprise(at)
            if owner is not None:
                return owner
        return None

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
    def load_from_file(cls, config_path: Path) -> Self:
        """Load and validate a config document from a TOML file.

        Entries live under `assets`. A document without an `assets` table is
        read in the deprecated layout, where the microgrid entries sit at the
        top level.

        Args:
            config_path: The path to the TOML configuration file.

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
        return loaded
