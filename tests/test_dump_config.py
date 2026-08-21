# License: MIT
# Copyright © 2025 Frequenz Energy-as-a-Service GmbH

"""Tests for serializing microgrid configs to TOML."""

import tomllib

from frequenz.gridpool.cli._dump_config import dump_map
from frequenz.gridpool.config import (
    ComponentTypeConfig,
    Metadata,
    MicrogridConfig,
    PVConfig,
)


def test_dump_map_round_trips() -> None:
    """A serialized config parses back to the same dotted-key structure."""
    configs = {
        10: MicrogridConfig(
            meta=Metadata(microgrid_id=10, name="Demo", latitude=52.5),
            ctype={
                "pv": ComponentTypeConfig(meter=[2], formula={"AC_POWER_ACTIVE": "#2"}),
            },
        )
    }

    parsed = tomllib.loads(dump_map(configs))

    assert parsed["10"]["meta"]["microgrid_id"] == 10
    assert parsed["10"]["meta"]["name"] == "Demo"
    assert parsed["10"]["meta"]["latitude"] == 52.5
    assert parsed["10"]["ctype"]["pv"]["meter"] == [2]
    assert parsed["10"]["ctype"]["pv"]["formula"]["AC_POWER_ACTIVE"] == "#2"


def test_dump_map_omits_empty_and_none() -> None:
    """Empty and None fields are dropped from the output."""
    configs = {7: MicrogridConfig(meta=Metadata(microgrid_id=7))}

    text = dump_map(configs)

    assert text == "7.meta.microgrid_id = 7\n"


def test_dump_map_empty() -> None:
    """An empty mapping serializes to an empty string."""
    assert dump_map({}) == ""


def test_dump_map_renders_whole_floats_as_underscored_ints() -> None:
    """Whole-number float fields (e.g. peak/rated power) render as `1_736_680`, not `1736680.0`."""
    configs = {
        10: MicrogridConfig(
            meta=Metadata(microgrid_id=10, latitude=52.5),
            pv={"1": PVConfig(peak_power=1_736_680.0, rated_power=1_400_000.0)},
        )
    }

    text = dump_map(configs)

    assert "10.pv.1.peak_power = 1_736_680\n" in text
    assert "10.pv.1.rated_power = 1_400_000\n" in text
    # Genuinely fractional floats are left alone.
    assert "10.meta.latitude = 52.5\n" in text
