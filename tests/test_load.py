# License: MIT
# Copyright © 2025 Frequenz Energy-as-a-Service GmbH

"""Tests for loading microgrid configs from the Assets API."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from frequenz.client.assets import AssetsApiClient
from frequenz.client.assets.electrical_component import (
    ComponentConnection,
    GridConnectionPoint,
    Meter,
    SolarInverter,
)
from frequenz.client.common.microgrid import MicrogridId
from frequenz.client.common.microgrid.electrical_components import ElectricalComponentId

from frequenz.gridpool import ComponentGraphConfig
from frequenz.gridpool._graph_generator import (
    ComponentGraphGenerator,
    MicrogridComponentGraph,
)
from frequenz.gridpool.config import load_configs
from frequenz.gridpool.config._load import (
    _derive_component_configs,
    _load_microgrids_from_api,
)


def _mock_client() -> MagicMock:
    """Mock an Assets API client for one microgrid: grid -> meter -> PV, + a meter."""
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
            Meter(id=ElectricalComponentId(3), microgrid_id=MicrogridId(10)),
            SolarInverter(id=ElectricalComponentId(4), microgrid_id=MicrogridId(10)),
        ]
    )
    client.list_microgrid_electrical_component_connections = AsyncMock(
        return_value=[
            ComponentConnection(
                source=ElectricalComponentId(1), destination=ElectricalComponentId(2)
            ),
            ComponentConnection(
                source=ElectricalComponentId(1), destination=ElectricalComponentId(3)
            ),
            ComponentConnection(
                source=ElectricalComponentId(2), destination=ElectricalComponentId(4)
            ),
        ]
    )
    return client


async def _build_graph(client: MagicMock) -> MicrogridComponentGraph:
    return await ComponentGraphGenerator(client).get_component_graph(MicrogridId(10))


async def test_load_microgrids_from_api_derives_formulas_and_ids() -> None:
    """A config loaded from the API gets both formulas and component IDs."""
    configs = await _load_microgrids_from_api(_mock_client(), [10])

    cfg = configs[10]
    assert cfg.ctype["pv"].formula == {"AC_POWER_ACTIVE": "COALESCE(#4, #2, 0.0)"}
    assert cfg.ctype["pv"].inverter == [4]
    assert cfg.ctype["pv"].meter == [2]
    assert cfg.ctype["grid"].meter == [2, 3]
    # Component types absent from the microgrid are not created.
    assert set(cfg.ctype) == {"grid", "consumption", "pv"}


async def test_load_microgrids_from_api_honours_the_component_graph_config() -> None:
    """A component graph config reaches the derived formulas."""
    configs = await _load_microgrids_from_api(
        _mock_client(),
        [10],
        component_graph_config=ComponentGraphConfig(
            prefer_meters_in_component_formulas=True
        ),
    )

    # Meter first, the opposite of the default order asserted above.
    ctype = configs[10].ctype
    assert ctype["pv"].formula == {"AC_POWER_ACTIVE": "COALESCE(#2, #4, 0.0)"}


async def test_load_configs_forwards_the_component_graph_config() -> None:
    """`load_configs` passes its component graph config down to the API layer."""
    configs = (
        await load_configs(
            assets_client=_mock_client(),
            microgrid_ids=[10],
            component_graph_config=ComponentGraphConfig(
                prefer_meters_in_component_formulas=True
            ),
        )
    ).microgrids

    assert configs[10].ctype["pv"].formula == {
        "AC_POWER_ACTIVE": "COALESCE(#2, #4, 0.0)"
    }


async def test_load_configs_rejects_a_component_graph_config_without_a_client() -> None:
    """A component graph config is only meaningful with an Assets API client."""
    with pytest.raises(ValueError, match="requires an assets_client"):
        await load_configs(
            default_files=[],
            component_graph_config=ComponentGraphConfig(),
        )


async def test_load_microgrids_from_api_keeps_metadata_when_graph_fails() -> None:
    """A graph-derivation failure still yields a metadata-only config."""
    client = _mock_client()
    client.list_microgrid_electrical_components = AsyncMock(
        side_effect=RuntimeError("graph unavailable")
    )

    configs = await _load_microgrids_from_api(client, [10])

    cfg = configs[10]
    assert cfg.meta.microgrid_id == 10
    assert cfg.ctype == {}


async def test_load_configs_validates_the_merged_whole(tmp_path: Path) -> None:
    """Layers are merged before validation, so an incomplete override is legal.

    The override omits `microgrid_id`, which would fail if its file were validated
    on its own; merged onto the default it completes and the whole validates once.
    """
    default = tmp_path / "default.toml"
    default.write_text(
        "assets.microgrids.1.meta.microgrid_id = 1\n"
        'assets.microgrids.1.meta.name = "Base"\n'
    )
    override = tmp_path / "override.toml"
    override.write_text('assets.microgrids.1.meta.name = "Override"\n')

    document = await load_configs(default_files=default, override_files=override)

    assert document.microgrids[1].meta.name == "Override"


async def test_load_configs_returns_the_whole_document(tmp_path: Path) -> None:
    """The file layers' relations and market locations survive the merge.

    The Assets API layer carries neither, so returning the whole `AssetsConfig`
    is what keeps topology from a file from being dropped.
    """
    default = tmp_path / "default.toml"
    default.write_text(
        "assets.microgrids.10.meta.microgrid_id = 10\n"
        'assets.microgrids.10.meta.name = "File name"\n'
        'assets.market_locations.51171875559.id = "51171875559"\n'
        "assets.relations.M10L51171875559.microgrid_id = 10\n"
        'assets.relations.M10L51171875559.market_location_id = "51171875559"\n'
    )

    document = await load_configs(default_files=default, assets_client=_mock_client())

    # The API layer filled the microgrid's component config.
    assert document.microgrids[10].ctype
    assert document.microgrids[10].meta.name == "File name"
    # The file's topology survived the merge with the API layer.
    assert "M10L51171875559" in document.relations
    assert "51171875559" in document.market_locations


async def test_derive_component_configs_builds_formulas_and_ids() -> None:
    """The builder derives formulas and IDs and omits types with neither."""
    graph = await _build_graph(_mock_client())

    configs = _derive_component_configs(graph)

    assert configs["pv"].formula == {"AC_POWER_ACTIVE": "COALESCE(#4, #2, 0.0)"}
    assert configs["pv"].inverter == [4]
    assert configs["pv"].meter == [2]
    assert configs["grid"].meter == [2, 3]
    assert set(configs) == {"grid", "consumption", "pv"}
