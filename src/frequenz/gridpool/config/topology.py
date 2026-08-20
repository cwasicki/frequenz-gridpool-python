# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Data model for market topology, as attributes of the entities.

Every link is an attribute of the side that has at most one partner: a market
location names its microgrid and its gridpool, and a microgrid without a market
location names its gridpool itself. A link that changes over time is written as
a table of periods instead of a single value.
"""

from dataclasses import field
from datetime import date
from typing import ClassVar, Type

from frequenz.client.assets import EnergyMarketCodeType, MarketLocationIdType
from marshmallow import Schema
from marshmallow_dataclass import dataclass


@dataclass(frozen=True)
class TimedRef:
    """A reference that holds for a period.

    Filed under a free label, which is never read or parsed. By convention it is
    the start date. Both bounds are inclusive, and an unset one is open.
    """

    id: int | None = None
    """The referenced entity."""

    start: date | None = None
    """First day the reference holds."""

    end: date | None = None
    """Last day the reference holds."""

    Schema: ClassVar[Type[Schema]] = Schema

    def __post_init__(self) -> None:
        """Check that the period is not inverted.

        Raises:
            ValueError: If it ends before it starts.
        """
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError(f"Period ends {self.end} before it starts {self.start}")

    def covers(self, day: date) -> bool:
        """Check whether this reference holds on a day.

        Args:
            day: The day to check.

        Returns:
            Whether the day falls within the period.
        """
        return (self.start is None or self.start <= day) and (
            self.end is None or day <= self.end
        )

    def overlaps(self, other: "TimedRef") -> bool:
        """Check whether two references share a day.

        Args:
            other: The reference to compare with.

        Returns:
            Whether the two periods overlap.
        """
        return (
            self.start is None or other.end is None or self.start <= other.end
        ) and (other.start is None or self.end is None or other.start <= self.end)


def resolve(
    scalar: int | None, timed: dict[str, TimedRef], at: date | None = None
) -> int | None:
    """Read a link that may be written as a value or as a table of periods.

    Args:
        scalar: The value form, which holds always.
        timed: The period form, keyed by label.
        at: Day to read the link on, or `None` for the only period there is.

    Returns:
        The referenced ID, or `None` when nothing holds.
    """
    if not timed:
        return scalar
    if at is None:
        return timed[sorted(timed, key=lambda k: timed[k].start or date.min)[-1]].id
    for ref in timed.values():
        if ref.covers(at):
            return ref.id
    return None


def check_periods(name: str, scalar: int | None, timed: dict[str, TimedRef]) -> None:
    """Check that a link uses one form and that its periods do not overlap.

    Args:
        name: What the link is called, for the message.
        scalar: The value form.
        timed: The period form.

    Raises:
        ValueError: If both forms are used at once, or if two periods overlap.
    """
    if timed and scalar is not None:
        raise ValueError(f"{name}: the period form replaces the plain value")
    refs = list(timed.values())
    for i, ref in enumerate(refs):
        for other in refs[i + 1 :]:
            if ref.overlaps(other):
                raise ValueError(
                    f"{name}: periods {ref.start}..{ref.end} and "
                    f"{other.start}..{other.end} overlap"
                )


# pylint: disable=too-many-instance-attributes
@dataclass(frozen=True)
class MarketLocationConfig:
    """Configuration of a market location.

    The identifier itself is the key this is filed under. The links to the
    microgrid, the gridpool and the enterprise sit here because a market
    location has at most one of each at a time.
    """

    type: MarketLocationIdType = MarketLocationIdType.MALO_ID
    """Identifier scheme of the market location."""

    delivery_area: str | None = None
    """Grid zone the connection point sits in."""

    delivery_area_type: EnergyMarketCodeType = EnergyMarketCodeType.EUROPE_EIC
    """Coding scheme of `delivery_area`."""

    microgrid_id: int | None = None
    """Microgrid this location meters."""

    microgrids: dict[str, TimedRef] = field(default_factory=dict)
    """Microgrids it metered over time, replacing `microgrid_id`."""

    gridpool_id: int | None = None
    """Gridpool this location takes part in."""

    gridpools: dict[str, TimedRef] = field(default_factory=dict)
    """Gridpools it took part in over time, replacing `gridpool_id`."""

    enterprise_id: int | None = None
    """Enterprise this location belongs to."""

    enterprises: dict[str, TimedRef] = field(default_factory=dict)
    """Enterprises it belonged to over time, replacing `enterprise_id`."""

    Schema: ClassVar[Type[Schema]] = Schema

    def __post_init__(self) -> None:
        """Check the schemes and the period forms.

        Raises:
            ValueError: If a scheme is unspecified, if a link uses both forms at
                once, or if two of its periods overlap.
        """
        if self.type is MarketLocationIdType.UNSPECIFIED:
            raise ValueError("Market location type must be specified")
        if self.delivery_area_type is EnergyMarketCodeType.UNSPECIFIED:
            raise ValueError("Delivery area code type must be specified")
        check_periods("microgrid", self.microgrid_id, self.microgrids)
        check_periods("gridpool", self.gridpool_id, self.gridpools)
        check_periods("enterprise", self.enterprise_id, self.enterprises)

    def microgrid(self, at: date | None = None) -> int | None:
        """Get the microgrid this location meters.

        Args:
            at: Day to read the link on, or `None` for the latest.

        Returns:
            The microgrid ID, or `None` when the location names none.
        """
        return resolve(self.microgrid_id, self.microgrids, at)

    def gridpool(self, at: date | None = None) -> int | None:
        """Get the gridpool this location takes part in.

        Args:
            at: Day to read the link on, or `None` for the latest.

        Returns:
            The gridpool ID, or `None` when the location names none.
        """
        return resolve(self.gridpool_id, self.gridpools, at)

    def enterprise(self, at: date | None = None) -> int | None:
        """Get the enterprise this location belongs to.

        Args:
            at: Day to read the link on, or `None` for the latest.

        Returns:
            The enterprise ID, or `None` when the location names none.
        """
        return resolve(self.enterprise_id, self.enterprises, at)
