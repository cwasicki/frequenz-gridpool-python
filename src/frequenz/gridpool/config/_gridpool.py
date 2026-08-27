# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Data model for a gridpool."""

from marshmallow_dataclass import dataclass


@dataclass
class GridpoolConfig:
    """Configuration of a gridpool."""

    gridpool_id: int
    """ID of the gridpool."""

    enterprise_id: int
    """Enterprise that owns the gridpool."""
