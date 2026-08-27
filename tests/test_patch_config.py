# License: MIT
# Copyright © 2025 Frequenz Energy-as-a-Service GmbH

"""Tests for in-place patching of existing dotted-key TOML config files."""

import pytest

from frequenz.gridpool.cli._patch_config import patch_text
from frequenz.gridpool.config import (
    ComponentTypeConfig,
    MicrogridConfig,
    PVConfig,
)

_ORIGINAL = """# EID 6 TOML configuration

assets.microgrids.40.name = "Bona - Auf dem Aurain"  #grid_side True
assets.microgrids.40.gid = 6
assets.microgrids.40.enterprise_id = 6
assets.microgrids.40.microgrid_id = 40
assets.microgrids.40.latitude = 50.39567065
assets.microgrids.40.longitude = 8.083947042665976
assets.microgrids.40.ctype.grid.meter = [87]
assets.microgrids.40.pv.1.peak_power = 616_140
assets.microgrids.40.pv.1.rated_power = 480_000 # https://example.com/technischedaten
"""


def test_fill_missing_is_a_noop_when_nothing_changed() -> None:
    """With `fill_missing`, values already on disk leave the file byte-identical."""
    configs = {
        40: MicrogridConfig(
            microgrid_id=40,
            latitude=50.39567065,
            pv={"1": PVConfig(peak_power=616_140.0, rated_power=480_000.0)},
        )
    }

    assert patch_text(_ORIGINAL, configs, fill_missing=True) == _ORIGINAL


def test_patch_overwrites_existing_leaf_by_default() -> None:
    """By default a managed leaf already on disk is refreshed to the new value."""
    configs = {
        40: MicrogridConfig(microgrid_id=40, pv={"1": PVConfig(rated_power=500_000.0)})
    }

    patched = patch_text(_ORIGINAL, configs)

    assert "assets.microgrids.40.pv.1.rated_power = 500_000" in patched
    assert "480_000" not in patched


def test_fill_missing_keeps_an_existing_leaf() -> None:
    """With `fill_missing`, an existing leaf keeps its on-disk value."""
    configs = {
        40: MicrogridConfig(microgrid_id=40, pv={"1": PVConfig(rated_power=500_000.0)})
    }

    patched = patch_text(_ORIGINAL, configs, fill_missing=True)

    assert "assets.microgrids.40.pv.1.rated_power = 480_000" in patched
    assert "500_000" not in patched


def test_patch_inserts_missing_leaf_next_to_existing_table() -> None:
    """A missing leaf under an existing table is inserted; everything else is untouched."""
    configs = {
        40: MicrogridConfig(microgrid_id=40, altitude=45.5),
    }

    patched = patch_text(_ORIGINAL, configs)

    lines = patched.splitlines()
    assert 'name = "Bona - Auf dem Aurain"  #grid_side True' in lines[2]
    # A genuinely fractional value is left alone.
    assert lines[3] == "assets.microgrids.40.altitude = 45.5"
    # Untouched lines are unchanged, including comments.
    assert (
        "assets.microgrids.40.pv.1.rated_power = 480_000 # "
        "https://example.com/technischedaten" in patched
    )
    assert "# EID 6 TOML configuration" in patched


def test_patch_appends_new_microgrid_at_the_end() -> None:
    """A microgrid id absent from the file is appended, blank-line separated."""
    configs = {
        9999: MicrogridConfig(microgrid_id=9999, name="Brand New"),
    }

    patched = patch_text(_ORIGINAL, configs)

    assert patched.startswith(_ORIGINAL)
    assert patched[len(_ORIGINAL) :] == (
        "\nassets.microgrids.9999.microgrid_id = 9_999\n"
        'assets.microgrids.9999.name = "Brand New"\n'
    )


def test_patch_inserts_new_subtable_next_to_its_microgrid() -> None:
    """A brand-new sub-table for an existing id lands next to that id's other lines."""
    configs = {
        40: MicrogridConfig(
            microgrid_id=40,
            pv={"2": PVConfig(peak_power=50_000.0)},
        ),
    }

    patched = patch_text(_ORIGINAL, configs)

    assert patched == _ORIGINAL + "assets.microgrids.40.pv.2.peak_power = 50_000\n"


def test_patch_inserts_new_subtables_for_multiple_microgrids() -> None:
    """Each microgrid's new sub-table lands next to its own lines, not all at the end."""
    original = _ORIGINAL + (
        '\nassets.microgrids.41.name = "Other Grid"\n'
        "assets.microgrids.41.microgrid_id = 41\n"
    )
    configs = {
        40: MicrogridConfig(
            microgrid_id=40,
            pv={"2": PVConfig(peak_power=50_000.0)},
        ),
        41: MicrogridConfig(
            microgrid_id=41,
            ctype={"grid": ComponentTypeConfig(meter=[1])},
        ),
    }

    patched = patch_text(original, configs)

    lines = patched.splitlines()
    assert lines[
        lines.index(
            "assets.microgrids.40.pv.1.rated_power = 480_000 # "
            "https://example.com/technischedaten"
        )
        + 1
    ] == ("assets.microgrids.40.pv.2.peak_power = 50_000")
    assert lines[-1] == "assets.microgrids.41.ctype.grid.meter = [1]"


def test_patch_refuses_top_level_layout() -> None:
    """A deprecated top-level file is refused, not duplicated into the new layout."""
    with pytest.raises(ValueError, match="top-level"):
        patch_text("1.microgrid_id = 1\n", {1: MicrogridConfig(microgrid_id=1)})


def test_patch_refuses_meta_layout() -> None:
    """A file nesting fields under `meta` is refused rather than patched alongside it."""
    original = (
        "assets.microgrids.1.microgrid_id = 1\n"
        'assets.microgrids.1.meta.name = "Old"\n'
    )
    with pytest.raises(ValueError, match="meta"):
        patch_text(original, {1: MicrogridConfig(microgrid_id=1)})


def test_patch_formats_new_numeric_leaves() -> None:
    """Newly inserted numeric leaves go through the same underscore formatting."""
    configs = {
        5555: MicrogridConfig(microgrid_id=5555, enterprise_id=1_234_567),
    }

    patched = patch_text(_ORIGINAL, configs)

    assert "assets.microgrids.5555.enterprise_id = 1_234_567\n" in patched
