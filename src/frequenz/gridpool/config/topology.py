# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Data model for market topology relations and the entities they connect.

Every link between assets is a relation. An entity carries only what is its
own, so a microgrid has a name and a position but neither a gridpool nor an
owner.
"""

from dataclasses import field
from datetime import date
from typing import ClassVar, Type

from frequenz.client.assets import EnergyMarketCodeType, MarketLocationIdType
from marshmallow import Schema
from marshmallow_dataclass import dataclass


@dataclass(frozen=True)
class MarketLocationConfig:
    """Configuration of a market location.

    The identifier itself is the key this is filed under; what is stored here is
    how to read it.
    """

    type: MarketLocationIdType = MarketLocationIdType.MALO_ID
    """Identifier scheme of the market location."""

    delivery_area: str | None = None
    """Grid zone the connection point sits in."""

    delivery_area_type: EnergyMarketCodeType = EnergyMarketCodeType.EUROPE_EIC
    """Coding scheme of `delivery_area`."""

    Schema: ClassVar[Type[Schema]] = Schema

    def __post_init__(self) -> None:
        """Check that the schemes are known ones.

        Raises:
            ValueError: If the identifier scheme or the code type is unspecified.
        """
        if self.type is MarketLocationIdType.UNSPECIFIED:
            raise ValueError("Market location type must be specified")
        if self.delivery_area_type is EnergyMarketCodeType.UNSPECIFIED:
            raise ValueError("Delivery area code type must be specified")


def relation_key(
    enterprise_id: int | None = None,
    gridpool_id: int | None = None,
    microgrid_id: int | None = None,
    market_location_id: str | None = None,
) -> str:
    """Derive the key a relation is filed under.

    Args:
        enterprise_id: Enterprise the relation belongs to.
        gridpool_id: Gridpool the relation names.
        microgrid_id: Microgrid the relation names.
        market_location_id: Market location the relation names.

    Returns:
        The key, with the segments of the unset sides omitted.
    """
    segments = (
        ("e", enterprise_id),
        ("g", gridpool_id),
        ("m", microgrid_id),
        ("l", market_location_id),
    )
    return "".join(
        f"{prefix}{value}" for prefix, value in segments if value is not None
    )


@dataclass(frozen=True)
class ValidityConfig:
    """A period a relation applies in.

    Filed under a free label, which is never read or parsed. By convention it is
    the start date. Both bounds are inclusive, and an unset one is open.
    """

    start: date | None = None
    """First day the relation applies."""

    end: date | None = None
    """Last day the relation applies."""

    Schema: ClassVar[Type[Schema]] = Schema

    def __post_init__(self) -> None:
        """Check that the period is not inverted.

        Raises:
            ValueError: If it ends before it starts.
        """
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError(f"Period ends {self.end} before it starts {self.start}")

    def covers(self, day: date) -> bool:
        """Check whether this period covers a day.

        Args:
            day: The day to check.

        Returns:
            Whether the day falls within the period.
        """
        return (self.start is None or self.start <= day) and (
            self.end is None or day <= self.end
        )

    def overlaps(self, other: "ValidityConfig") -> bool:
        """Check whether two periods share a day.

        Args:
            other: The period to compare with.

        Returns:
            Whether the two periods overlap.
        """
        return (
            self.start is None or other.end is None or self.start <= other.end
        ) and (other.start is None or self.end is None or other.start <= self.end)


@dataclass(frozen=True)
class RelationConfig:
    """A relation between an enterprise and the assets it owns or operates.

    A record naming one asset besides its enterprise says who owns it, and one
    naming several says how they are connected.

    The key it is filed under defines which relation it is,
    `e<enterprise>g<gridpool>m<microgrid>l<market_location>` with the segments of
    the unset sides dropped. It clusters the lines of one record and is never
    read: every value comes from the fields, and `AssetsConfig.check` verifies
    that the two agree.
    """

    enterprise_id: int | None = None
    """Enterprise the relation belongs to."""

    gridpool_id: int | None = None
    """Gridpool participating in this relation."""

    microgrid_id: int | None = None
    """Microgrid participating in this relation."""

    market_location_id: str | None = None
    """Market location participating in this relation."""

    start: date | None = None
    """First day the relation applies, open when unset."""

    end: date | None = None
    """Last day the relation applies, open when unset."""

    validity: dict[str, ValidityConfig] = field(default_factory=dict)
    """Periods the relation applies in, for the rare case of more than one.

    Replaces `start` and `end` rather than adding to them.
    """

    Schema: ClassVar[Type[Schema]] = Schema

    def __post_init__(self) -> None:
        """Check the combinations of sides the market topology allows.

        A gridpool relation missing its delivery area is only warned about: the
        Assets API requires one, but a relation whose area is not established yet
        is still worth recording.

        A record may be incomplete here, since an override names only the fields
        it changes. `AssetsConfig.check` looks at the merged result.

        Raises:
            ValueError: If both period forms are used at once, or if two periods
                overlap.
        """
        if self.validity and (self.start is not None or self.end is not None):
            raise ValueError(
                f"Relation {self.key}: `validity` replaces `start` and `end`, "
                "so give one form or the other"
            )
        periods = self.periods
        for i, period in enumerate(periods):
            for other in periods[i + 1 :]:
                if period.overlaps(other):
                    raise ValueError(
                        f"Relation {self.key}: periods {period.start}..{period.end} "
                        f"and {other.start}..{other.end} overlap"
                    )

    @property
    def is_complete(self) -> bool:
        """Whether this record names an enterprise and at least one of its assets."""
        return self.enterprise_id is not None and bool(self.assets)

    @property
    def key(self) -> str:
        """The key this relation belongs under, derived from its own fields."""
        return relation_key(
            self.enterprise_id,
            self.gridpool_id,
            self.microgrid_id,
            self.market_location_id,
        )

    @property
    def assets(self) -> dict[str, int | str]:
        """The assets this relation names, the enterprise aside."""
        named = {
            "gridpool_id": self.gridpool_id,
            "microgrid_id": self.microgrid_id,
            "market_location_id": self.market_location_id,
        }
        return {kind: value for kind, value in named.items() if value is not None}

    @property
    def is_ownership(self) -> bool:
        """Whether this relation only says who owns a single asset."""
        return len(self.assets) == 1

    @property
    def periods(self) -> list[ValidityConfig]:
        """The periods this relation applies in, both forms normalised into one.

        A relation with neither form applies always, which is one open period.
        """
        if self.validity:
            return sorted(self.validity.values(), key=lambda p: p.start or date.min)
        return [ValidityConfig(start=self.start, end=self.end)]

    def covers(self, day: date) -> bool:
        """Check whether this relation applies on a day.

        Args:
            day: The day to check.

        Returns:
            Whether any of its periods covers the day.
        """
        return any(period.covers(day) for period in self.periods)

    def overlaps(self, other: "RelationConfig") -> bool:
        """Check whether two relations apply at the same time.

        Args:
            other: The relation to compare with.

        Returns:
            Whether any of their periods overlap.
        """
        return any(a.overlaps(b) for a in self.periods for b in other.periods)

    def matches(  # pylint: disable=too-many-arguments
        self,
        *,
        enterprise_id: int | None = None,
        gridpool_id: int | None = None,
        microgrid_id: int | None = None,
        market_location_id: str | None = None,
        at: date | None = None,
    ) -> bool:
        """Check whether this relation has all the given sides.

        Args:
            enterprise_id: Enterprise to match, or `None` to ignore.
            gridpool_id: Gridpool to match, or `None` to ignore.
            microgrid_id: Microgrid to match, or `None` to ignore.
            market_location_id: Market location to match, or `None` to ignore.
            at: Day the relation must apply on, or `None` to ignore.

        Returns:
            Whether every side given matches this relation.
        """
        return (
            (enterprise_id is None or enterprise_id == self.enterprise_id)
            and (gridpool_id is None or gridpool_id == self.gridpool_id)
            and (microgrid_id is None or microgrid_id == self.microgrid_id)
            and (
                market_location_id is None
                or market_location_id == self.market_location_id
            )
            and (at is None or self.covers(at))
        )
