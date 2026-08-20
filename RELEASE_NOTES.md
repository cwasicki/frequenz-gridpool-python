# Frequenz Gridpool Library Release Notes

## Summary

<!-- Here goes a general summary of what this release is about -->

## Upgrading

- `MicrogridConfig.load_from_file` is replaced by `AssetsConfig.load_from_file`,
  which returns the whole document rather than just its microgrids:

  ```python
  configs = AssetsConfig.load_from_file(path).microgrids
  ```

  `load_configs` is unchanged. `load_configs_from_files` now merges entries of
  the same microgrid across files field by field, where it used to let the last
  file replace the whole entry.

## New Features

- `AssetsConfig` gives the `assets` namespace a type, so the entities still to
  come are added as fields rather than as more dict lookups. Entries are checked
  against the ID they are filed under wherever the class is loaded, not only via
  `load_from_file`.

  Entity tables a version does not know are ignored with a warning, so a reader
  keeps working against files that already carry newer entities.

- The `assets` namespace now carries the market topology in `assets.relations`,
  one record per link between an enterprise and the assets it owns or operates,
  mirroring `MarketTopologyRelation` of the Assets API. A record is filed under a
  key naming every side, so it only writes what the key cannot say:

  ```toml
  assets.relations.e80g80m241l10208446344.enterprise_id = 80
  assets.relations.e80g80m241l10208446344.gridpool_id = 80
  assets.relations.e80g80m241l10208446344.microgrid_id = 241
  assets.relations.e80g80m241l10208446344.market_location_id = "10208446344"

  assets.market_locations.10208446344.delivery_area = "10YDE-RWENET---I"
  ```

  The key defines which relation a line belongs to and is never read for its
  values: a record states its own sides, and `AssetsConfig.check` verifies that
  the two agree.

  `enterprise_id` is required and at least one asset must be named, so a record
  naming a single asset states who owns it and one naming several states how
  they are connected. Entities hold no foreign keys, so `meta.gid` and
  `meta.enterprise_id` are superseded, though they still load.

  The delivery area is not a foreign key but the grid zone a connection point
  sits in, so it stays on the entity: on the market location, or on the
  microgrid when there is none. `AssetsConfig.delivery_area(relation)` resolves
  it in that order.

  A relation applies always unless it carries `start` and `end`. For the rare
  pairing that applies in more than one period, `validity` replaces them:

  ```toml
  assets.relations.e80g80m241l10208446344.validity.initial.end = 2026-06-30
  assets.relations.e80g80m241l10208446344.validity.metering_issue.start = 2026-09-01
  ```

  The label is never read or parsed; any string does, by convention the start
  date. Periods may not overlap, and no asset may have two owners at once.

  `AssetsConfig.find_relations` searches by any combination of sides and by the
  day they apply on, leaving ownership records out unless asked for them.
  `type` and `delivery_area_type` of a market location are the
  `MarketLocationIdType` and `EnergyMarketCodeType` enums of
  `frequenz-client-assets`, written by name and defaulting to the German malo
  and the EIC codes.

- `load_assets_from_files` reads several files into one document and
  `merge_assets_configs` layers two, so the relations of a gridpool can be spread
  over files. `AssetsConfig.check` runs over the merged result rather than over
  each file, since a file that overrides a single field is incomplete on its own;
  `load_from_file` still checks by default and takes `check=False` for one layer
  of several.

## Bug Fixes

<!-- Here goes notable bug fixes that are worth a special mention or explanation -->
