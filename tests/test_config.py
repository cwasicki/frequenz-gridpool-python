# License: MIT
# Copyright © 2025 Frequenz Energy-as-a-Service GmbH

"""Tests for the frequenz.lib.notebooks.config module."""

import logging
from pathlib import Path
from typing import Any

import pytest
from marshmallow import ValidationError
from pytest_mock import MockerFixture

from frequenz.gridpool.config import (
    AssetsConfig,
    ComponentTypeConfig,
    MicrogridConfig,
    load_configs,
)

VALID_CONFIG: dict[str, dict[str, Any]] = {
    "1": {
        "meta": {"name": "Test Grid", "gid": 1, "microgrid_id": 1},
        "ctype": {
            "pv": {"meter": [101, 102], "formula": {"AC_POWER_ACTIVE": "#12+#23"}},
            "battery": {
                "inverter": [201, 202, 203],
                "component": [301, 302, 303, 304, 305, 306],
            },
        },
        "pv": {
            "PV1": {"peak_power": 5000, "rated_power": 4500},
            "PV2": {"peak_power": 8000, "rated_power": 7000},
        },
        "battery": {
            "BAT1": {"capacity": 10000},
            "BAT2": {"capacity": 12000},
            "BAT3": {"capacity": 8000},
            "BAT4": {"capacity": 15000},
            "BAT5": {"capacity": 20000},
            "BAT6": {},
        },
    },
}


@pytest.fixture
def valid_microgrid_config() -> MicrogridConfig:
    """Fixture to provide a valid MicrogridConfig instance."""
    # pylint: disable=protected-access
    return MicrogridConfig._load_table_entries(VALID_CONFIG)[1]


def test_is_valid_type() -> None:
    """Test the validation of component types."""
    assert ComponentTypeConfig.is_valid_type("pv")
    assert not ComponentTypeConfig.is_valid_type("unknown")


def test_component_type_config_cids() -> None:
    """Test the retrieval of component IDs for various configurations."""
    config = ComponentTypeConfig(inverter=[1, 2, 3])
    assert config.cids() == [1, 2, 3]

    config = ComponentTypeConfig(meter=[4, 5], inverter=[1, 2, 3])
    assert config.cids() == [4, 5]


def test_microgrid_config_init(valid_microgrid_config: MicrogridConfig) -> None:
    """Test initialisation of MicrogridConfig with valid configuration data."""
    assert valid_microgrid_config.meta is not None
    assert valid_microgrid_config.meta.name == "Test Grid"
    pv_config = valid_microgrid_config.pv
    assert pv_config is not None
    pv_system = pv_config.get("PV1")
    assert pv_system is not None
    assert pv_system.peak_power == 5000


def test_microgrid_config_component_types(
    valid_microgrid_config: MicrogridConfig,
) -> None:
    """Test retrieval of all component types in the configuration."""
    assert valid_microgrid_config.component_types() == ["pv", "battery"]


def test_microgrid_config_component_type_ids(
    valid_microgrid_config: MicrogridConfig,
) -> None:
    """Test retrieval of component IDs for a given component type."""
    assert valid_microgrid_config.component_type_ids("pv") == [101, 102]
    assert valid_microgrid_config.component_type_ids("battery") == [201, 202, 203]
    assert valid_microgrid_config.component_type_ids("battery", "inverter") == [
        201,
        202,
        203,
    ]
    assert valid_microgrid_config.component_type_ids("battery", "component") == [
        301,
        302,
        303,
        304,
        305,
        306,
    ]

    with pytest.raises(ValueError):
        valid_microgrid_config.component_type_ids("unknown")


def test_microgrid_config_formula(valid_microgrid_config: MicrogridConfig) -> None:
    """Test retrieval of formula for a given component type and metric."""
    assert valid_microgrid_config.formula("pv", "AC_POWER_ACTIVE") == "#12+#23"

    with pytest.raises(ValueError):
        valid_microgrid_config.formula("pv", "INVALID_METRIC")


def test_load_configs(mocker: MockerFixture) -> None:
    """Test loading configurations for multiple microgrids from mock TOML files."""
    toml_data = """
    1.meta.microgrid_id = 1
    1.meta.name = "Test Grid"
    1.meta.gid = 1
    1.ctype.pv.meter = [101, 102]
    1.ctype.battery.inverter = [201, 202, 203]
    1.ctype.battery.component = [301, 302, 303, 304, 305, 306]
    1.pv.PV1.peak_power = 5000
    1.pv.PV1.rated_power = 4500
    1.pv.PV2.peak_power = 8000
    1.pv.PV2.rated_power = 7000
    1.battery.BAT1.capacity = 10000
    """
    mock_file = mocker.mock_open(read_data=toml_data.encode("utf-8"))
    mocker.patch("pathlib.Path.open", mock_file)
    mocker.patch("pathlib.Path.is_file", mocker.Mock(return_value=True))
    configs = AssetsConfig.load_from_files(Path("mock_path.toml")).microgrids

    assert 1 in configs
    assert configs[1].meta is not None
    assert configs[1].meta.name == "Test Grid"

    pv_config = configs[1].pv
    assert pv_config is not None
    pv_system = pv_config.get("PV1")
    assert pv_system is not None
    assert pv_system.peak_power == 5000

    battery_config = configs[1].battery
    assert battery_config is not None
    battery_system = battery_config.get("BAT1")
    assert battery_system is not None
    assert battery_system.capacity == 10000


def _assert_optional_field(value: float | None, expected: float) -> None:
    """Validate an optional field.

    Args:
        value: The optional field value to check.
        expected: The expected value to assert if `value` is not None.

    Raises:
        AssertionError: If `value` is not None and does not match `expected`.
    """
    if value is not None:
        if value != expected:
            raise AssertionError(f"Expected {expected}, got {value}")


_PREFIXED_TOML = """
assets.microgrids.1.meta.microgrid_id = 1
assets.microgrids.1.meta.name = "Test Grid"
assets.microgrids.1.ctype.pv.meter = [101, 102]
"""

_LEGACY_TOML = """
1.meta.microgrid_id = 1
1.meta.name = "Test Grid"
1.ctype.pv.meter = [101, 102]
"""


def _write(tmp_path: Path, name: str, text: str) -> Path:
    """Write `text` to `name` under `tmp_path` and return the path."""
    path = tmp_path / name
    path.write_text(text)
    return path


def test_load_prefixed(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Entries under `assets.microgrids` load without a deprecation warning."""
    configs = AssetsConfig.load_from_files(
        _write(tmp_path, "prefixed.toml", _PREFIXED_TOML)
    ).microgrids

    assert configs[1].meta.name == "Test Grid"
    assert configs[1].component_type_ids("pv") == [101, 102]
    assert "deprecated" not in caplog.text


def test_load_legacy_warns(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Top-level entries still load, but warn and name the file."""
    path = _write(tmp_path, "legacy.toml", _LEGACY_TOML)

    with caplog.at_level(logging.WARNING):
        configs = AssetsConfig.load_from_files(path).microgrids

    assert configs[1].meta.name == "Test Grid"
    assert "deprecated" in caplog.text
    assert str(path) in caplog.text


def test_load_mixed_layouts_rejected(tmp_path: Path) -> None:
    """A half-migrated file with both layouts is an error, not a merge."""
    path = _write(
        tmp_path,
        "mixed.toml",
        _PREFIXED_TOML + '2.meta.microgrid_id = 2\n2.meta.name = "Other Grid"\n',
    )

    with pytest.raises(ValueError, match="outside `assets`"):
        AssetsConfig.load_from_files(path)


def test_load_assets_without_microgrids(tmp_path: Path) -> None:
    """An `assets` table without microgrids yields no configs and no warning."""
    path = _write(tmp_path, "other.toml", 'assets.gridpool.7.name = "GP"\n')

    assert not AssetsConfig.load_from_files(path).microgrids


async def test_merge_prefixed_base_with_legacy_override(tmp_path: Path) -> None:
    """Layers of either layout merge as usual, since layout is resolved on load."""
    base = _write(tmp_path, "base.toml", _PREFIXED_TOML)
    override = _write(
        tmp_path, "override.toml", '1.meta.microgrid_id = 1\n1.meta.name = "Renamed"\n'
    )

    configs = (
        await load_configs(default_files=base, override_files=override)
    ).microgrids

    assert configs[1].meta.name == "Renamed"
    assert configs[1].component_type_ids("pv") == [101, 102]


def test_load_from_files_layers_fields(tmp_path: Path) -> None:
    """Later files override fields without replacing the microgrid entry."""
    base = _write(tmp_path, "base.toml", _PREFIXED_TOML)
    override = _write(
        tmp_path,
        "override.toml",
        "assets.microgrids.1.meta.microgrid_id = 1\n"
        'assets.microgrids.1.meta.name = "Renamed"\n',
    )

    configs = AssetsConfig.load_from_files([base, override]).microgrids

    assert configs[1].meta.name == "Renamed"
    assert configs[1].component_type_ids("pv") == [101, 102]


def test_assets_config_rejects_mismatched_id() -> None:
    """An entry filed under the wrong ID is rejected wherever it is loaded."""
    with pytest.raises(ValueError, match="Microgrid ID mismatch"):
        AssetsConfig.Schema().load(
            {"microgrids": {"23": {"meta": {"microgrid_id": 99}}}}
        )


def test_metadata_delivery_area_removed() -> None:
    """Delivery areas live on topology relations, not microgrid metadata."""
    with pytest.raises(ValidationError, match="Unknown field"):
        AssetsConfig.Schema().load(
            {
                "microgrids": {
                    "23": {"meta": {"microgrid_id": 23, "delivery_area": "area"}}
                }
            }
        )


def test_assets_config_warns_on_unknown_entities(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Entity tables this version does not know are skipped, but reported."""
    path = _write(
        tmp_path, "future.toml", _PREFIXED_TOML + 'assets.gridpool.7.name = "GP"\n'
    )

    with caplog.at_level(logging.WARNING):
        config = AssetsConfig.load_from_files(path)

    assert sorted(config.microgrids) == [1]
    assert "gridpool" in caplog.text
