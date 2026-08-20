# License: MIT
# Copyright © 2025 Frequenz Energy-as-a-Service GmbH

"""Microgrid configuration data model and loading."""

from frequenz.microgrid_component_graph import ComponentGraphConfig, FormulaOverrides

from .assets import AssetsConfig
from .load import (
    load_assets_from_files,
    load_configs,
    load_configs_from_api,
    load_configs_from_files,
)
from .microgrid import (
    BatteryConfig,
    ComponentCategory,
    ComponentType,
    ComponentTypeConfig,
    Metadata,
    MicrogridConfig,
    PVConfig,
    WindConfig,
    merge_config_maps,
    merge_microgrid_configs,
)
from .topology import (
    MarketLocationConfig,
    RelationConfig,
    ValidityConfig,
    relation_key,
)

__all__ = [
    "AssetsConfig",
    "BatteryConfig",
    "ComponentCategory",
    "ComponentGraphConfig",
    "ComponentType",
    "ComponentTypeConfig",
    "FormulaOverrides",
    "MarketLocationConfig",
    "Metadata",
    "MicrogridConfig",
    "PVConfig",
    "RelationConfig",
    "ValidityConfig",
    "WindConfig",
    "load_assets_from_files",
    "load_configs",
    "load_configs_from_api",
    "load_configs_from_files",
    "merge_config_maps",
    "merge_microgrid_configs",
    "relation_key",
]
