# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Tests for the market topology, written as attributes of the entities."""

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from frequenz.gridpool.config import AssetsConfig

_TOML = """
assets.market_locations.10208446344.enterprise_id = 80
assets.market_locations.10208446344.gridpool_id = 80
assets.market_locations.10208446344.microgrid_id = 241
assets.market_locations.10208446344.delivery_area = "10YDE-RWENET---I"

assets.market_locations.50506333827.enterprise_id = 80
assets.market_locations.50506333827.gridpool_id = 80
assets.market_locations.50506333827.microgrid_id = 252
assets.market_locations.50506333827.delivery_area = "10YDE-RWENET---I"

assets.market_locations.51171875559.enterprise_id = 80
assets.market_locations.51171875559.gridpool_id = 80
assets.market_locations.51171875559.delivery_area = "10YDE-EON------1"

assets.microgrids.242.meta.microgrid_id = 242
assets.microgrids.242.meta.enterprise_id = 80
assets.microgrids.242.meta.gid = 80
assets.microgrids.242.meta.delivery_area = "10YDE-RWENET---I"
"""


def _load(**tables: Any) -> AssetsConfig:
    """Load a document straight from its tables."""
    loaded = AssetsConfig.Schema().load(tables)
    assert isinstance(loaded, AssetsConfig)
    return loaded


def _config(tmp_path: Path) -> AssetsConfig:
    """Load the shared example document."""
    path = tmp_path / "assets.toml"
    path.write_text(_TOML)
    return AssetsConfig.load_from_file(path)


def test_links_sit_on_the_market_location(tmp_path: Path) -> None:
    """A location names its microgrid, gridpool, enterprise and zone."""
    location = _config(tmp_path).market_location("10208446344")

    assert location.microgrid() == 241
    assert location.gridpool() == 80
    assert location.enterprise() == 80
    assert location.delivery_area == "10YDE-RWENET---I"


def test_microgrid_links_come_from_its_locations(tmp_path: Path) -> None:
    """A microgrid's gridpool and zone are read off the locations metering it."""
    config = _config(tmp_path)

    assert config.market_locations_of(241) == ["10208446344"]
    assert config.gridpool_of(241) == 80
    assert config.delivery_area_of(241) == "10YDE-RWENET---I"
    assert config.enterprise_of(241) == 80


def test_microgrid_without_a_location_names_them_itself(tmp_path: Path) -> None:
    """The same questions are answered from the microgrid when no location does."""
    config = _config(tmp_path)

    assert config.market_locations_of(242) == []
    assert config.gridpool_of(242) == 80
    assert config.delivery_area_of(242) == "10YDE-RWENET---I"
    assert config.enterprise_of(242) == 80


def test_location_without_a_microgrid(tmp_path: Path) -> None:
    """A location can take part in a gridpool without metering a microgrid."""
    location = _config(tmp_path).market_location("51171875559")

    assert location.microgrid() is None
    assert location.gridpool() == 80


def test_link_may_change_over_time() -> None:
    """A link that changes is written as periods instead of a value."""
    config = _load(
        market_locations={
            "10208446344": {
                "microgrids": {
                    "initial": {"id": 241, "end": date(2026, 2, 28)},
                    "moved": {"id": 265, "start": date(2026, 3, 1)},
                }
            }
        }
    )
    location = config.market_location("10208446344")

    assert location.microgrid(date(2026, 1, 1)) == 241
    assert location.microgrid(date(2026, 6, 1)) == 265
    assert config.market_locations_of(241, date(2026, 1, 1)) == ["10208446344"]
    assert config.market_locations_of(241, date(2026, 6, 1)) == []


def test_owner_may_change_over_time() -> None:
    """Ownership uses the same period form."""
    config = _load(
        microgrids={
            "999": {
                "meta": {
                    "microgrid_id": 999,
                    "enterprises": {
                        "initial": {"id": 10, "end": date(2026, 2, 28)},
                        "sold": {"id": 44, "start": date(2026, 3, 1)},
                    },
                }
            }
        }
    )

    assert config.enterprise_of(999, date(2026, 1, 1)) == 10
    assert config.enterprise_of(999, date(2026, 6, 1)) == 44


def test_both_forms_rejected() -> None:
    """The period form replaces the plain value rather than adding to it."""
    with pytest.raises(ValueError, match="replaces the plain value"):
        _load(
            market_locations={
                "10208446344": {
                    "microgrid_id": 241,
                    "microgrids": {"moved": {"id": 265}},
                }
            }
        )


def test_overlapping_periods_rejected() -> None:
    """A link cannot hold two values on the same day."""
    with pytest.raises(ValueError, match="overlap"):
        _load(
            market_locations={
                "10208446344": {
                    "microgrids": {
                        "initial": {"id": 241, "end": date(2026, 6, 30)},
                        "moved": {"id": 265, "start": date(2026, 6, 1)},
                    }
                }
            }
        )


def test_microgrid_in_two_gridpools_has_no_single_answer() -> None:
    """What the model cannot say: one microgrid, two gridpools at once."""
    config = _load(
        market_locations={
            "1": {"microgrid_id": 241, "gridpool_id": 80},
            "2": {"microgrid_id": 241, "gridpool_id": 46},
        }
    )

    assert config.market_locations_of(241) == ["1", "2"]
    with pytest.raises(ValueError, match="name gridpools"):
        config.gridpool_of(241)
