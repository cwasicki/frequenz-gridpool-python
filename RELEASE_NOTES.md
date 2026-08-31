# Frequenz Gridpool Library Release Notes

## Summary

This release rounds out `gridpool-cli` for the `assets` config layout and adds
gridpool enterprise ownership to the config model. The CLI can now generate,
validate, patch, and query merged config files.

## Upgrading

- `generate-config` now writes the `assets.microgrids` layout and stamps
  `assets.version`, instead of the legacy layout. Regenerate configs to get the
  current format; generated files then load back without a migration.

- `generate-config --inplace` refuses legacy-layout files (top-level or
  `meta`-nested), which it would duplicate rather than edit. Rebuild those from
  scratch.

## New Features

- `gridpool-cli validate <files>` checks config files offline and exits
  non-zero on the first error, to gate config-repo CI. Each file must be valid
  on its own, so a record names its own key and required fields; the files are
  then checked merged, for the cross-record checks.

- `gridpool-cli` accepts `FREQUENZ_API_KEY` and `FREQUENZ_API_SECRET` as a
  fallback pair for `ASSETS_API_AUTH_KEY` and `ASSETS_API_SIGN_SECRET`.

- Gridpools are described under `assets.gridpools`, each entry naming the
  enterprise that owns the gridpool. `AssetsConfig.find_enterprise(gridpool_id)`
  returns the configured owner.
  `gridpool-cli find-enterprise <gridpool_id> <files>` prints it from the config.
  `AssetsConfig.check` enforces the one-enterprise-per-gridpool invariant: a
  gridpool's microgrids may not disagree on it, and a declared enterprise must
  match the inferred one.

- A config derived from the Assets API now carries each microgrid's
  `enterprise_id`.

- `generate-config --inplace` refreshes managed values while preserving
  formatting; `--fill-missing` only adds absent values. Generated patches are
  validated before writing.

## Bug Fixes

- Config files with validity periods now load under marshmallow 3, not only
  marshmallow 4. `tomllib` yields native `datetime` objects, which marshmallow
  3's `DateTime` field rejected. `marshmallow` is now a direct dependency so the
  minimum-version test exercises this path.
