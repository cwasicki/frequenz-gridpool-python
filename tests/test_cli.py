# License: MIT
# Copyright © 2025 Frequenz Energy-as-a-Service GmbH

"""Tests for the gridpool CLI."""

from unittest.mock import AsyncMock, MagicMock, patch

from asyncclick.testing import CliRunner
from frequenz.client.assets import AssetsApiClient
from frequenz.client.assets.electrical_component import (
    ComponentConnection,
    GridConnectionPoint,
    Meter,
    SolarInverter,
)
from frequenz.client.common.microgrid import MicrogridId
from frequenz.client.common.microgrid.electrical_components import ElectricalComponentId

from frequenz.gridpool.cli.__main__ import _graph_config, cli

_ENV = {
    "ASSETS_API_URL": "grpc://localhost",
    "ASSETS_API_AUTH_KEY": "key",
    "ASSETS_API_SIGN_SECRET": "secret",
}


def _mock_client() -> MagicMock:
    """Mock an Assets API client: grid 1 -> meter 2 -> solar inverter 4."""
    client = MagicMock(spec=AssetsApiClient)
    client.get_microgrid = AsyncMock(return_value=MagicMock(location=None))
    client.list_microgrid_electrical_components = AsyncMock(
        return_value=[
            GridConnectionPoint(
                id=ElectricalComponentId(1),
                microgrid_id=MicrogridId(10),
                rated_fuse_current=100,
            ),
            Meter(id=ElectricalComponentId(2), microgrid_id=MicrogridId(10)),
            SolarInverter(id=ElectricalComponentId(4), microgrid_id=MicrogridId(10)),
        ]
    )
    client.list_microgrid_electrical_component_connections = AsyncMock(
        return_value=[
            ComponentConnection(
                source=ElectricalComponentId(1), destination=ElectricalComponentId(2)
            ),
            ComponentConnection(
                source=ElectricalComponentId(2), destination=ElectricalComponentId(4)
            ),
        ]
    )
    return client


def _patched_client() -> MagicMock:
    """Patch `AssetsApiClient` so the CLI's `async with` yields the mock."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=_mock_client())
    ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=ctx)


async def test_print_formulas_prefer_meters_flips_the_order() -> None:
    """The flag makes the CLI print the meter first."""
    with patch("frequenz.gridpool.cli.__main__.AssetsApiClient", _patched_client()):
        result = await CliRunner().invoke(
            cli,
            ["print-formulas", "10", "--prefer-meters-in-component-formulas"],
            env=_ENV,
        )

    assert result.exit_code == 0, result.output
    assert 'pv = "COALESCE(#2, #4, 0.0)"' in result.output


async def test_generate_config_prefer_meters_flips_the_order() -> None:
    """The flag reaches the formulas written into the config."""
    with patch("frequenz.gridpool.cli.__main__.AssetsApiClient", _patched_client()):
        result = await CliRunner().invoke(
            cli,
            ["generate-config", "10", "--prefer-meters-in-component-formulas"],
            env=_ENV,
        )

    assert result.exit_code == 0, result.output
    assert (
        '10.ctype.pv.formula.AC_POWER_ACTIVE = "COALESCE(#2, #4, 0.0)"' in result.output
    )


async def test_freq_api_env_vars_are_accepted_as_fallbacks() -> None:
    """`FREQUENZ_API_{KEY,SECRET}` stand in when the `ASSETS_API_*` vars are unset."""
    env = {
        "ASSETS_API_URL": "grpc://localhost",
        "ASSETS_API_AUTH_KEY": None,
        "ASSETS_API_SIGN_SECRET": None,
        "FREQUENZ_API_KEY": "freq-key",
        "FREQUENZ_API_SECRET": "freq-secret",
    }
    client = _patched_client()
    with patch("frequenz.gridpool.cli.__main__.AssetsApiClient", client):
        result = await CliRunner().invoke(cli, ["print-formulas", "10"], env=env)

    assert result.exit_code == 0, result.output
    client.assert_called_once_with(
        "grpc://localhost", auth_key="freq-key", sign_secret="freq-secret"
    )


async def test_partial_assets_credentials_are_not_mixed_with_fallbacks() -> None:
    """A half-set `ASSETS_API_*` pair is not completed from `FREQUENZ_API_*`."""
    env = {
        "ASSETS_API_URL": "grpc://localhost",
        "ASSETS_API_AUTH_KEY": "key",
        "ASSETS_API_SIGN_SECRET": None,
        "FREQUENZ_API_KEY": "freq-key",
        "FREQUENZ_API_SECRET": "freq-secret",
    }
    result = await CliRunner().invoke(cli, ["print-formulas", "10"], env=env)

    assert result.exit_code != 0, result.output


async def test_missing_credentials_fail_with_a_readable_message() -> None:
    """With no credentials set the command exits non-zero and names the vars."""
    env = {
        "ASSETS_API_URL": "grpc://localhost",
        "ASSETS_API_AUTH_KEY": None,
        "ASSETS_API_SIGN_SECRET": None,
        "FREQUENZ_API_KEY": None,
        "FREQUENZ_API_SECRET": None,
    }
    result = await CliRunner().invoke(cli, ["print-formulas", "10"], env=env)

    assert result.exit_code != 0
    assert "FREQUENZ_API_KEY" in result.output


def test_graph_config_is_none_without_the_flag() -> None:
    """With no flag no config is built, so the library's defaults apply."""
    assert _graph_config(False) is None
