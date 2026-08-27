# Frequenz Gridpool Library Release Notes

## Summary

<!-- Here goes a general summary of what this release is about -->

## Upgrading

- `MicrogridConfig.load_from_file` is replaced by `AssetsConfig.load_from_files`,
  which loads one or more files, merged into one document, and returns the whole
  document rather than just its microgrids:

  ```python
  configs = AssetsConfig.load_from_files(path).microgrids
  ```

  `load_configs` now returns the whole `AssetsConfig` rather than just its
  microgrids, so the file layers' `relations` and `market_locations` survive the
  merge; replace `load_configs(...)` with `load_configs(...).microgrids` where
  only the microgrid map is needed. `load_from_files` layers files field by field
  instead of replacing a complete microgrid entry; fields omitted by a later file
  retain the value from the earlier layer and cannot be removed by omission.

- `Metadata` is removed; its fields (`microgrid_id`, `name`, `gid`, coordinates,
  times) now sit directly on `MicrogridConfig`:

  ```python
  MicrogridConfig(microgrid_id=1, name="Grid")  # was meta=Metadata(...)
  ```

  In TOML they move up one level, `assets.microgrids.1.name` rather than
  `assets.microgrids.1.meta.name`. A file still nesting a microgrid's fields
  under `meta` loads, lifted with a deprecation warning.

- A microgrid's `delivery_area` is removed. Move its value to a relation's
  `delivery_area.code`, and set `delivery_area.code_type` when the code is not
  EIC. When relations are present, the legacy `gid` must be their sole
  gridpool ID; remove it for a microgrid that participates in several gridpools.

- `load_configs_from_files` is removed. Use `AssetsConfig.load_from_files`,
  which returns the whole document rather than just its microgrids: replace
  `load_configs_from_files(files)` with
  `AssetsConfig.load_from_files(files).microgrids`, or use the returned
  `AssetsConfig` directly to keep relations and market locations.

- `load_configs_from_api` is now private. For an API-only load call
  `load_configs(assets_client=..., microgrid_ids=...)` and read its `.microgrids`.

- `merge_config_maps` and `merge_microgrid_configs` are removed. Layering is now
  done on the raw tables before loading, inside `load_configs` and
  `AssetsConfig.load_from_files`; pass all the layers to one of those instead of
  merging loaded objects.

- Relation validity bounds and `at` query instants must include a UTC offset.

- The implementation modules `config.load` and `config.microgrid` are now
  private. Import their public names from `frequenz.gridpool.config` instead.

- Microgrids are now keyed by `int` microgrid ID, not `str`. This covers
  `AssetsConfig.microgrids`, including documents returned by `load_configs`.
  Index the mapping by integer ID:

  ```python
  configs[1]  # was configs["1"]
  ```

- The `AC_ACTIVE_POWER` deprecation warning is dropped. Use `AC_POWER_ACTIVE`
  as the formula metric key; the old name is no longer flagged on load.


## New Features

- `gridpool-cli validate <files>` checks config files offline and exits
  non-zero on the first error, to gate config-repo CI. Each file must be valid
  on its own, so a record names its own key and required fields; the files are
  then checked merged, for the cross-record checks.

- `AssetsConfig` gives the `assets` namespace a type, so the entities still to
  come are added as fields rather than as more dict lookups. Microgrid IDs are
  checked during construction. `AssetsConfig.check()` performs the topology-wide
  checks after all layers have been merged; the file loaders call it unless
  `AssetsConfig.load_from_files` is passed `check=False`.

  File loaders ignore unknown entity tables with a warning, so a reader keeps
  working against files that already carry newer entities.

  The `assets` table may carry a `version`; on load a document is run through a
  migration pipeline that brings older layouts up to the current format, so
  legacy files keep working. The version tracks the assets format alone, not
  the whole document.

- Market topology is described under `assets.relations`, based on the Assets
  API `MarketTopologyRelation`: each record links at least two of a gridpool, a
  microgrid and a market location, filed under a
  `G<gridpool_id>M<microgrid_id>L<market_location_id>` key derived from its own
  sides. A relation naming a gridpool sits in a `delivery_area` that rides on
  the relation, so a gridpool-to-microgrid relation with no market location still
  carries one. A relation's validity lives in `validity`, each entry a half-open
  `[start, end)` datetime period it applies over. Use-case-specific periods
  qualify a relation; separate relations let one microgrid participate in
  several gridpools. The config extends the API with plain periods for relations
  that do not distinguish use cases. A gridpool-free microgrid-to-market-location
  relation may also carry a delivery area for a direct mapping. Market locations
  live under `assets.market_locations` as self-describing entries carrying their
  own identifier, how to read it (`MALO_ID` by default), and the Assets API market
  area (`EU_DE` by default). A relation's `delivery_area` is a `code` plus a
  `code_type` that defaults to EIC, so an EIC area is just
  `delivery_area.code = "..."`; EIC codes are check-character-validated. Raw
  market-location IDs must be unique within a document, including across market
  areas.

  `AssetsConfig` answers the common lookups with `find_relations` and the
  projections `find_delivery_areas`, `find_market_locations` and
  `find_microgrids`, each filtered by the other sides and an instant.

  Time-varying enterprise ownership is outside this change;
  `MicrogridConfig.enterprise_id` remains as a scalar field.

- `gridpool-cli` accepts `FREQUENZ_API_KEY` and `FREQUENZ_API_SECRET` as a
  fallback pair for `ASSETS_API_AUTH_KEY` and `ASSETS_API_SIGN_SECRET`.

- Gridpools are described under `assets.gridpools`, each entry naming the
  enterprise that owns the gridpool. `AssetsConfig.find_enterprise(gridpool_id)`
  returns the owner: a declared `gridpools` entry if present, otherwise the
  enterprise inferred from the gridpool's microgrids.
  `gridpool-cli find-enterprise <gridpool_id> <files>` prints it from the config.

- A config derived from the Assets API now carries each microgrid's
  `enterprise_id`.

## Bug Fixes

- Layering config files no longer resets a field a later file leaves unset back
  to its default. The raw tables are merged before they are loaded.

<!-- Here goes notable bug fixes that are worth a special mention or explanation -->
