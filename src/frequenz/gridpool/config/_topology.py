# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Data model for market topology relations.

A relation links a gridpool, a microgrid and a market location, based on the
Assets API `MarketTopologyRelation`. It names at least two of the three, and its
participations say which market use cases it serves and over which periods. The
config also supports plain validity periods and delivery-area mappings without
a gridpool.

Ownership of an asset by an enterprise is deliberately left out: it is not a
topology link but an exclusive, time-varying property of the asset, and will be
modelled on the asset itself.
"""

from dataclasses import field
from datetime import datetime
from typing import ClassVar, Type

from frequenz.client.assets import (
    EnergyMarketCodeType,
    MarketLocationIdType,
    MarketParticipationType,
)
from marshmallow import Schema
from marshmallow_dataclass import dataclass

from ._fields import toml_datetime_metadata

_EIC_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-"
_MARKET_AREA_EU_DE = 101


def _require_offset_aware(value: datetime, name: str) -> None:
    """Reject a datetime that does not identify an absolute instant."""
    if value.utcoffset() is None:
        raise ValueError(f"{name} must include a UTC offset, got {value}")


def _require_eic(value: str) -> None:
    """Reject a malformed EIC code or an invalid check character.

    See the ENTSO-E EIC Data Exchange Implementation Guide for the check-character
    algorithm:
    https://eepublicdownloads.entsoe.eu/clean-documents/EDI/Library/cim_based/EIC_Data_Exchange_IG_v1.2.pdf
    """
    valid_format = (
        len(value) == 16
        and value[-1] != "-"
        and all(char in _EIC_ALPHABET for char in value)
    )
    if valid_format:
        checksum = sum(
            (16 - index) * _EIC_ALPHABET.index(char)
            for index, char in enumerate(value[:15])
        )
        check_character = _EIC_ALPHABET[36 - ((checksum - 1) % 37)]
        if value[-1] == check_character:
            return
    raise ValueError(f"Delivery area must be a valid EIC code, got {value!r}")


@dataclass(frozen=True)
class MarketLocationConfig:
    """Configuration of a market location.

    Mirrors the Assets API `MarketLocationRef`: the market area, identifier `id`
    and how to read it. `id` repeats the key it is filed under, so the object is
    self-describing; `AssetsConfig.check` verifies the two agree. The grid zone
    the location sits in is not kept here but on the relations that name it. Raw
    IDs must be unique within a document, including across market areas.
    """

    id: str | None = None
    """The market location identifier."""

    type: MarketLocationIdType = MarketLocationIdType.MALO_ID
    """Identifier scheme of the market location."""

    market_area: int = _MARKET_AREA_EU_DE
    """Assets API market area, defaulting to EU_DE (`101`)."""

    Schema: ClassVar[Type[Schema]] = Schema

    def __post_init__(self) -> None:
        """Check that the identifier scheme and market area are specified.

        Raises:
            ValueError: If the identifier scheme or market area is unspecified.
        """
        if self.type is MarketLocationIdType.UNSPECIFIED:
            raise ValueError("Market location type must be specified")
        if self.market_area <= 0:
            raise ValueError("Market area must be specified")


@dataclass(frozen=True)
class DeliveryAreaConfig:
    """Configuration of a delivery area.

    Mirrors the Assets API `DeliveryArea`: a grid-zone `code` and the `code_type`
    that says how to read it. `code_type` defaults to EIC, so the common case is
    just a code. An EIC code is checked for valid syntax and check character;
    other code types are taken as given.
    """

    code: str | None = None
    """The delivery-area code."""

    code_type: EnergyMarketCodeType = EnergyMarketCodeType.EUROPE_EIC
    """Identifier scheme of the code, defaulting to EIC."""

    Schema: ClassVar[Type[Schema]] = Schema

    def __post_init__(self) -> None:
        """Check the code against its type.

        Raises:
            ValueError: If the code type is unspecified, no code is given, or an
                EIC code is malformed.
        """
        if self.code_type is EnergyMarketCodeType.UNSPECIFIED:
            raise ValueError("Delivery area code type must be specified")
        if self.code is None:
            raise ValueError("Delivery area must name a code")
        if self.code_type is EnergyMarketCodeType.EUROPE_EIC:
            _require_eic(self.code)


def _relation_key(
    gridpool_id: int | None = None,
    microgrid_id: int | None = None,
    market_location_id: str | None = None,
) -> str:
    """Derive the key a relation is filed under.

    Args:
        gridpool_id: Gridpool the relation names.
        microgrid_id: Microgrid the relation names.
        market_location_id: Market location the relation names.

    Returns:
        The key, with the segments of the unset sides omitted.
    """
    segments = (
        ("G", gridpool_id),
        ("M", microgrid_id),
        ("L", market_location_id),
    )
    return "".join(
        f"{prefix}{value}" for prefix, value in segments if value is not None
    )


@dataclass(frozen=True)
class ValidityConfig:
    """A period a relation applies over, optionally a market use case.

    A period naming a `participation` is a market participation, which applies
    only to a gridpool relation; one without is a plain validity window. Filed
    under a free label, which is never read or parsed. The half-open interval
    `[start, end)` mirrors the Assets API: the start is inclusive, the end
    exclusive, and an unset bound is open.
    """

    participation: MarketParticipationType | None = None
    """The market use case, unset for a plain validity window."""

    start: datetime | None = field(default=None, metadata=toml_datetime_metadata())
    """Inclusive start of the period."""

    end: datetime | None = field(default=None, metadata=toml_datetime_metadata())
    """Exclusive end of the period."""

    Schema: ClassVar[Type[Schema]] = Schema

    def __post_init__(self) -> None:
        """Check the use case, bounds and order of the period.

        Raises:
            ValueError: If the use case is unspecified, a bound has no UTC
                offset, or the period ends at or before it starts.
        """
        if self.participation is MarketParticipationType.UNSPECIFIED:
            raise ValueError(
                "Participation is unspecified; name a use case or leave it unset "
                "for a plain period"
            )
        if self.start is not None:
            _require_offset_aware(self.start, "Period start")
        if self.end is not None:
            _require_offset_aware(self.end, "Period end")
        # Reject an empty `[t, t)` window: it covers no instant, yet `overlaps`
        # would still report it as overlapping a period around `t`.
        if self.start is not None and self.end is not None and self.end <= self.start:
            raise ValueError(
                f"Period ends {self.end} at or before it starts {self.start}"
            )

    def covers(self, at: datetime) -> bool:
        """Check whether this period applies at an instant.

        Args:
            at: The instant to check.

        Returns:
            Whether the instant falls within the half-open period.
        """
        _require_offset_aware(at, "Instant")
        return (self.start is None or self.start <= at) and (
            self.end is None or at < self.end
        )

    def overlaps(self, other: "ValidityConfig") -> bool:
        """Check whether two periods share an instant.

        Args:
            other: The period to compare with.

        Returns:
            Whether the two half-open periods overlap.
        """
        return (self.start is None or other.end is None or self.start < other.end) and (
            other.start is None or self.end is None or other.start < self.end
        )


@dataclass(frozen=True)
class RelationConfig:
    """A relation between a gridpool, a microgrid and a market location.

    It names at least two of the three. The key it is filed under is
    `G<gridpool>M<microgrid>L<market_location>` with the segments of the unset
    sides dropped. The key clusters the lines of one record and is never read:
    every value comes from the fields, and `AssetsConfig.check` verifies that the
    two agree.

    A relation naming a gridpool sits in a `delivery_area`; the grid zone rides
    on the relation, not on the market location, so a gridpool-to-microgrid
    relation with no market location still carries one. A gridpool-free
    microgrid-to-market-location relation may also carry one to map that market
    location to its delivery area. A delivery area names its code type, which
    defaults to EIC.

    Its validity lives in `validity`, each entry a period the relation applies
    over. A period naming a market use case tells the relation's gridpool
    participations apart; one without is a plain window, for a relation that
    serves a single use or none, such as a bare microgrid-to-market-location
    metering relation. A relation with no periods applies at all times.
    """

    gridpool_id: int | None = None
    """Gridpool participating in this relation."""

    microgrid_id: int | None = None
    """Microgrid participating in this relation."""

    market_location_id: str | None = None
    """Market location participating in this relation."""

    delivery_area: DeliveryAreaConfig | None = None
    """Delivery area this relation sits in; required once a gridpool is named."""

    validity: dict[str, ValidityConfig] = field(default_factory=dict)
    """Periods this relation applies over, each optionally a market use case."""

    Schema: ClassVar[Type[Schema]] = Schema

    def __post_init__(self) -> None:
        """Check the periods against the relation.

        A record may be incomplete here, since an override names only the fields
        it changes; `AssetsConfig.check` looks at the merged result.

        Raises:
            ValueError: If a period names a market use case without a gridpool,
                or periods of one use case overlap.
        """
        by_use: dict[MarketParticipationType | None, list[ValidityConfig]] = {}
        for period in self.validity.values():
            if period.participation is not None and self.gridpool_id is None:
                raise ValueError(
                    f"Relation {self.key}: a {period.participation.name} "
                    "participation applies only to a gridpool relation"
                )
            by_use.setdefault(period.participation, []).append(period)
        for use, group in by_use.items():
            label = use.name if use is not None else "untyped"
            for i, period in enumerate(group):
                for other in group[i + 1 :]:
                    if period.overlaps(other):
                        raise ValueError(
                            f"Relation {self.key}: {label} periods "
                            f"{period.start}..{period.end} and "
                            f"{other.start}..{other.end} overlap"
                        )

    @property
    def key(self) -> str:
        """The key this relation belongs under, derived from its own fields."""
        return _relation_key(
            self.gridpool_id, self.microgrid_id, self.market_location_id
        )

    @property
    def is_complete(self) -> bool:
        """Whether this relation names at least two of the three sides."""
        sides = (self.gridpool_id, self.microgrid_id, self.market_location_id)
        return sum(side is not None for side in sides) >= 2

    def covers(self, at: datetime) -> bool:
        """Check whether this relation applies at an instant.

        Args:
            at: The instant to check.

        Returns:
            Whether any of its periods covers the instant, or `True` when it
            lists none and so applies always.
        """
        _require_offset_aware(at, "Instant")
        if not self.validity:
            return True
        return any(period.covers(at) for period in self.validity.values())

    def matches(
        self,
        *,
        gridpool_id: int | None = None,
        microgrid_id: int | None = None,
        market_location_id: str | None = None,
        delivery_area: str | DeliveryAreaConfig | None = None,
        participation: MarketParticipationType | None = None,
        at: datetime | None = None,
    ) -> bool:
        """Check whether this relation has all the given sides.

        Args:
            gridpool_id: Gridpool to match, or `None` to ignore.
            microgrid_id: Microgrid to match, or `None` to ignore.
            market_location_id: Market location to match, or `None` to ignore.
            delivery_area: Delivery area to match, either a `DeliveryAreaConfig`
                matched on code and code type, or a bare code string matched on
                code alone; `None` to ignore.
            participation: Use case the relation must serve, or `None` to ignore.
            at: Instant the relation, or the given participation, must apply at,
                or `None` to ignore.

        Returns:
            Whether every side given matches this relation.
        """
        if at is not None:
            _require_offset_aware(at, "Instant")
        if gridpool_id is not None and gridpool_id != self.gridpool_id:
            return False
        if microgrid_id is not None and microgrid_id != self.microgrid_id:
            return False
        if market_location_id is not None and (
            market_location_id != self.market_location_id
        ):
            return False
        if delivery_area is not None:
            if self.delivery_area is None:
                return False
            if isinstance(delivery_area, DeliveryAreaConfig):
                if delivery_area != self.delivery_area:
                    return False
            elif delivery_area != self.delivery_area.code:
                return False
        if participation is not None:
            served = [
                p for p in self.validity.values() if p.participation == participation
            ]
            if not served or (at is not None and not any(p.covers(at) for p in served)):
                return False
        elif at is not None and not self.covers(at):
            return False
        return True
