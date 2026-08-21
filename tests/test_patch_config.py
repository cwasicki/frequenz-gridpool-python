# License: MIT
# Copyright © 2025 Frequenz Energy-as-a-Service GmbH

"""Tests for in-place patching of existing dotted-key TOML config files."""

from frequenz.gridpool.cli._patch_config import patch_text
from frequenz.gridpool.config import (
    ComponentTypeConfig,
    Metadata,
    MicrogridConfig,
    PVConfig,
)

_ORIGINAL = """# EID 6 TOML configuration

40.meta.name = "Bona - Auf dem Aurain"  #grid_side True
40.meta.gid = 6
40.meta.enterprise_id = 6
40.meta.microgrid_id = 40
40.meta.latitude = 50.39567065
40.meta.longitude = 8.083947042665976
40.ctype.grid.meter = [87]
40.pv.1.peak_power = 616_140
40.pv.1.rated_power = 480_000 # https://example.com/technischedaten
"""


def test_patch_is_a_noop_when_nothing_changed() -> None:
    """Patching with values already on disk leaves the file byte-identical."""
    configs = {
        40: MicrogridConfig(
            meta=Metadata(microgrid_id=40, latitude=50.39567065),
            pv={"1": PVConfig(peak_power=616_140.0, rated_power=480_000.0)},
        )
    }

    assert patch_text(_ORIGINAL, configs) == _ORIGINAL


def test_patch_inserts_missing_leaf_next_to_existing_table() -> None:
    """A missing leaf under an existing table is inserted; everything else is untouched."""
    configs = {
        40: MicrogridConfig(meta=Metadata(microgrid_id=40, altitude=45.5)),
    }

    patched = patch_text(_ORIGINAL, configs)

    lines = patched.splitlines()
    assert 'name = "Bona - Auf dem Aurain"  #grid_side True' in lines[2]
    # A genuinely fractional value is left alone.
    assert lines[3] == "40.meta.altitude = 45.5"
    # Untouched lines are unchanged, including comments.
    assert (
        "40.pv.1.rated_power = 480_000 # https://example.com/technischedaten" in patched
    )
    assert "# EID 6 TOML configuration" in patched


def test_patch_appends_new_microgrid_at_the_end() -> None:
    """A microgrid id absent from the file is appended, blank-line separated."""
    configs = {
        9999: MicrogridConfig(meta=Metadata(microgrid_id=9999, name="Brand New")),
    }

    patched = patch_text(_ORIGINAL, configs)

    assert patched.startswith(_ORIGINAL)
    assert patched[len(_ORIGINAL) :] == (
        '\n9999.meta.microgrid_id = 9_999\n9999.meta.name = "Brand New"\n'
    )


def test_patch_inserts_new_subtable_next_to_its_microgrid() -> None:
    """A brand-new sub-table for an existing id lands next to that id's other lines."""
    configs = {
        40: MicrogridConfig(
            meta=Metadata(microgrid_id=40),
            pv={"2": PVConfig(peak_power=50_000.0)},
        ),
    }

    patched = patch_text(_ORIGINAL, configs)

    assert patched == _ORIGINAL + "40.pv.2.peak_power = 50_000\n"


def test_patch_inserts_new_subtables_for_multiple_microgrids() -> None:
    """Each microgrid's new sub-table lands next to its own lines, not all at the end."""
    original = _ORIGINAL + '\n41.meta.name = "Other Grid"\n41.meta.microgrid_id = 41\n'
    configs = {
        40: MicrogridConfig(
            meta=Metadata(microgrid_id=40),
            pv={"2": PVConfig(peak_power=50_000.0)},
        ),
        41: MicrogridConfig(
            meta=Metadata(microgrid_id=41),
            ctype={"grid": ComponentTypeConfig(meter=[1])},
        ),
    }

    patched = patch_text(original, configs)

    lines = patched.splitlines()
    assert lines[
        lines.index(
            "40.pv.1.rated_power = 480_000 # https://example.com/technischedaten"
        )
        + 1
    ] == ("40.pv.2.peak_power = 50_000")
    assert lines[-1] == "41.ctype.grid.meter = [1]"


def test_patch_formats_new_numeric_leaves() -> None:
    """Newly inserted numeric leaves go through the same underscore formatting."""
    configs = {
        5555: MicrogridConfig(
            meta=Metadata(microgrid_id=5555, enterprise_id=1_234_567)
        ),
    }

    patched = patch_text(_ORIGINAL, configs)

    assert "5555.meta.enterprise_id = 1_234_567\n" in patched
