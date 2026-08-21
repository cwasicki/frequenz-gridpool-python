# License: MIT
# Copyright © 2025 Frequenz Energy-as-a-Service GmbH

"""Loading and merging of asset configurations."""

import logging
from pathlib import Path
from typing import Any

from frequenz.client.assets import AssetsApiClient
from frequenz.client.common.microgrid import MicrogridId
from frequenz.microgrid_component_graph import ComponentGraphConfig

from .._graph_generator import (
    ComponentGraphGenerator,
    MicrogridComponentGraph,
    battery_ids,
    battery_inverter_ids,
    battery_meter_ids,
    chp_ids,
    chp_meter_ids,
    ev_charger_ids,
    ev_charger_meter_ids,
    grid_meter_ids,
    pv_inverter_ids,
    pv_meter_ids,
)
from ._assets import AssetsConfig, _deep_merge, _merge_file_tables
from ._microgrid import (
    ComponentTypeConfig,
    Metadata,
    MicrogridConfig,
)

_logger = logging.getLogger(__name__)


async def load_configs(
    default_files: str | Path | list[str | Path] | None = None,
    assets_client: AssetsApiClient | None = None,
    override_files: str | Path | list[str | Path] | None = None,
    microgrid_ids: list[int] | None = None,
    component_graph_config: ComponentGraphConfig | None = None,
) -> AssetsConfig:
    """Load configs from up to three sources and merge them in layers.

    Combines up to three sources, listed here from lowest to highest
    precedence: a *default* config file layer, the Assets API, and an
    *override* config file layer.  Higher layers win on conflicts, while
    lower layers fill in anything the higher ones leave unset.  This lets
    callers pick a strategy by choosing which sources to pass, for example:

    - `default_files` + `assets_client`: files provide defaults that the
      Assets API overrides.
    - `assets_client` + `override_files`: the Assets API provides the base
      that files override.
    - all three: the Assets API sits between a default and an override file
      layer.

    The microgrid IDs fetched from the Assets API are `microgrid_ids` when
    given, otherwise the IDs found in the default and override files.  This
    lets the Assets API layer be used even when no files are given.

    Args:
        default_files:
            Optional path or list of paths to config files forming the
            lowest-precedence layer.
        assets_client:
            Optional Assets API client.  When given, microgrid metadata and
            formulas are fetched and layered above the default files.
        override_files:
            Optional path or list of paths to config files forming the
            highest-precedence layer.
        microgrid_ids:
            Optional explicit microgrid IDs to fetch from the Assets API.
            When given, these replace the IDs derived from the files, so the
            Assets API layer can be used without any files.
        component_graph_config:
            How to build the component graph and generate its formulas.  See
            `ComponentGraphConfig`.  Defaults to that class's own defaults.
            Requires an `assets_client`.

    Returns:
        The merged document. Use `.microgrids` for just the microgrid map; the
        file layers may also contribute `relations` and `market_locations`,
        which the Assets API layer does not provide.

    Raises:
        ValueError: If none of the three sources is provided, if `microgrid_ids`
            or `component_graph_config` is given without an `assets_client`, or
            if a file's `assets.microgrids` is not a table.
    """
    if default_files is None and assets_client is None and override_files is None:
        raise ValueError("At least one config source must be provided.")

    if microgrid_ids is not None and assets_client is None:
        raise ValueError("microgrid_ids requires an assets_client.")

    if component_graph_config is not None and assets_client is None:
        raise ValueError("component_graph_config requires an assets_client.")

    default_table: dict[str, Any] = {}
    if default_files is not None:
        default_table = _merge_file_tables(default_files)

    override_table: dict[str, Any] = {}
    if override_files is not None:
        override_table = _merge_file_tables(override_files)

    merged = default_table
    if assets_client is not None:
        if microgrid_ids is None:
            file_ids: set[str] = set()
            for table in (default_table, override_table):
                microgrids = table.get("microgrids", {})
                if not isinstance(microgrids, dict):
                    raise ValueError(
                        f"`assets.microgrids` must be a table, got {type(microgrids)}"
                    )
                file_ids |= set(microgrids)
            microgrid_ids = sorted(int(mid) for mid in file_ids)
        assets_configs = await _load_microgrids_from_api(
            assets_client=assets_client,
            microgrid_ids=microgrid_ids,
            component_graph_config=component_graph_config,
        )
        schema = MicrogridConfig.Schema()
        api_table: dict[str, Any] = {
            "microgrids": {
                str(mid): schema.dump(cfg) for mid, cfg in assets_configs.items()
            }
        }
        merged = _deep_merge(merged, api_table)

    merged = _deep_merge(merged, override_table)

    loaded = AssetsConfig.Schema().load(merged)
    assert isinstance(loaded, AssetsConfig)
    loaded.check()
    return loaded


async def _load_microgrids_from_api(
    assets_client: AssetsApiClient,
    microgrid_ids: list[int],
    component_graph_config: ComponentGraphConfig | None = None,
) -> dict[int, "MicrogridConfig"]:
    """Load microgrid configs from the Assets API.

    For each microgrid, fetches its location metadata (latitude, longitude) and
    then derives the per-type formulas and meter/inverter/component IDs from its
    component graph. Builds the Assets API layer that `load_configs` merges; for
    an API-only load call `load_configs(assets_client=..., microgrid_ids=...)`.

    The two steps fail independently: a microgrid whose metadata cannot be
    fetched is skipped, while one whose component graph cannot be derived is
    still returned with metadata only. Both failures are logged as warnings.

    Args:
        assets_client:
            Assets API client used to fetch microgrid metadata and the
            component graph.
        microgrid_ids:
            List of microgrid IDs to load configurations for.
        component_graph_config:
            How to build the component graph and generate its formulas.  See
            `ComponentGraphConfig`.  Defaults to that class's own defaults.

    Returns:
        dict[int, MicrogridConfig]:
            Mapping from microgrid ID to the loaded `MicrogridConfig` instance.
            Microgrids whose metadata could not be loaded are omitted, so the
            returned mapping may cover fewer microgrids than were requested.
    """
    generator = ComponentGraphGenerator(assets_client, config=component_graph_config)
    configs: dict[int, MicrogridConfig] = {}
    for microgrid_id in microgrid_ids:
        try:
            cfg = await _build_config_from_metadata(assets_client, microgrid_id)
        except Exception as exc:  # pylint: disable=broad-except
            _logger.warning(
                "Failed to load microgrid %s metadata from the Assets API: %s",
                microgrid_id,
                exc,
            )
            continue

        try:
            graph = await generator.get_component_graph(MicrogridId(microgrid_id))
            cfg.ctype = _derive_component_configs(graph)
        except Exception as exc:  # pylint: disable=broad-except
            _logger.warning(
                "Failed to derive component config for microgrid %s from the "
                "graph: %s",
                microgrid_id,
                exc,
            )

        configs[microgrid_id] = cfg

    return configs


async def _build_config_from_metadata(
    assets_client: AssetsApiClient, microgrid_id: int
) -> MicrogridConfig:
    """Build a base config for a microgrid from its Assets API metadata.

    Fetches the microgrid's location and returns a `MicrogridConfig` carrying
    only metadata; formulas are derived separately.

    Args:
        assets_client: Assets API client used to fetch the microgrid.
        microgrid_id: ID of the microgrid to fetch.

    Returns:
        A `MicrogridConfig` with metadata from the Assets API.
    """
    mgrid = await assets_client.get_microgrid(MicrogridId(microgrid_id))
    location = mgrid.location if mgrid.location else None
    return MicrogridConfig(
        meta=Metadata(
            microgrid_id=microgrid_id,
            latitude=location.latitude if location else None,
            longitude=location.longitude if location else None,
        )
    )


def _derive_component_configs(
    graph: MicrogridComponentGraph,
) -> dict[str, ComponentTypeConfig]:
    """Build the component-type configs for a microgrid from its graph.

    Derives, per component type, the `AC_POWER_ACTIVE` formula and the
    meter/inverter/component ID lists straight from the component graph. A
    component type only appears in the result if the graph yields a non-zero
    formula or at least one ID for it.

    Args:
        graph:
            Component graph to derive the configuration from.

    Returns:
        Mapping from component type to its derived `ComponentTypeConfig`.
    """

    def as_formula(derived: str) -> dict[str, str] | None:
        """Wrap a derived formula for storage, or drop it if empty or zero.

        Component types absent from the microgrid yield an empty or
        constant-zero formula (e.g. `0.0`), which is not worth storing.
        """
        stripped = derived.strip()
        try:
            if not stripped or float(stripped) == 0.0:
                return None
        except ValueError:
            pass
        return {"AC_POWER_ACTIVE": derived}

    configs: dict[str, ComponentTypeConfig] = {
        "consumption": ComponentTypeConfig(
            meter=None,
            inverter=None,
            component=None,
            formula=as_formula(graph.consumer_formula()),
        ),
        "grid": ComponentTypeConfig(
            meter=grid_meter_ids(graph) or None,
            inverter=None,
            component=None,
            formula=as_formula(graph.grid_formula()),
        ),
        "pv": ComponentTypeConfig(
            meter=pv_meter_ids(graph) or None,
            inverter=pv_inverter_ids(graph) or None,
            component=None,
            formula=as_formula(graph.pv_formula(None)),
        ),
        "battery": ComponentTypeConfig(
            meter=battery_meter_ids(graph) or None,
            inverter=battery_inverter_ids(graph) or None,
            component=battery_ids(graph) or None,
            formula=as_formula(graph.battery_formula(None)),
        ),
        "chp": ComponentTypeConfig(
            meter=chp_meter_ids(graph) or None,
            inverter=None,
            component=chp_ids(graph) or None,
            formula=as_formula(graph.chp_formula(None)),
        ),
        "ev": ComponentTypeConfig(
            meter=ev_charger_meter_ids(graph) or None,
            inverter=None,
            component=ev_charger_ids(graph) or None,
            formula=as_formula(graph.ev_charger_formula(None)),
        ),
    }

    return {
        component_type: cfg
        for component_type, cfg in configs.items()
        if cfg.formula or cfg.meter or cfg.inverter or cfg.component
    }
