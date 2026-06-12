# Frequenz Gridpool Library Release Notes

## Summary

This release adds a new Assets API based configuration loader, introduces helpers to merge microgrid configs, and updates PV curtailability behavior to support unspecified values.

## Upgrading

<!-- Here goes notes on how to upgrade from previous versions, including deprecations and what they should be replaced with -->

## New Features

* Added `MicrogridConfig.load_configs_from_assets_api(...)` to load microgrid metadata (latitude/longitude) from the Assets API and optionally populate formulas from the component graph. Formulas are derived for all supported component types by default, and a microgrid that cannot be loaded is logged and skipped rather than aborting the whole batch.
* Added `merge_microgrid_configs(...)` for deep-merging two `MicrogridConfig` objects where override values take precedence and `None` does not overwrite base values.
* Added `merge_config_maps(...)` for merging two dictionaries of microgrid configs by microgrid ID.

## Bug Fixes

<!-- Here goes notable bug fixes that are worth a special mention or explanation -->
