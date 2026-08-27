# Frequenz Gridpool Library

[![Build Status](https://github.com/frequenz-floss/frequenz-gridpool-python/actions/workflows/ci.yaml/badge.svg)](https://github.com/frequenz-floss/frequenz-gridpool-python/actions/workflows/ci.yaml)
[![PyPI Package](https://img.shields.io/pypi/v/frequenz-gridpool)](https://pypi.org/project/frequenz-gridpool/)
[![Docs](https://img.shields.io/badge/docs-latest-informational)](https://frequenz-floss.github.io/frequenz-gridpool-python/)

## Introduction

High-level interface to gridpools for the Frequenz platform.

## Market topology configuration

Market topology is stored under the `assets` namespace. A relation names at
least two of a gridpool, microgrid and market location:

```toml
assets.microgrids.241.meta.microgrid_id = 241

assets.market_locations.10208446344.id = "10208446344"

assets.relations.G80M241L10208446344.gridpool_id = 80
assets.relations.G80M241L10208446344.microgrid_id = 241
assets.relations.G80M241L10208446344.market_location_id = "10208446344"
assets.relations.G80M241L10208446344.delivery_area.code = "10YDE-RWENET---I"
assets.relations.G80M241L10208446344.validity.trading.participation = "ENERGY_TRADING"
assets.relations.G80M241L10208446344.validity.trading.start = 2026-01-01T00:00:00Z
```

A relation naming a gridpool requires a delivery area. A gridpool-free relation
must link a microgrid and market location, and may carry a delivery area for a
direct market-location-to-area mapping. Omitted market-location types default
to `MALO_ID`; omitted market areas default to `101` (`EU_DE`).

A delivery area is a `code` and a `code_type` that defaults to EIC, so an EIC
area is just `delivery_area.code = "..."`. EIC codes are checked for format and
check character, not registration with an EIC issuing office; other code types
are taken as given. One code is bound to a single code type across a document.

Validity periods are half-open: the start is inclusive, the end exclusive, and
an omitted bound is open. Bounds and query instants must include a UTC offset.

Load one or more files and query the merged document with:

```python
from datetime import datetime, timezone
from pathlib import Path

from frequenz.gridpool.config import AssetsConfig

config = AssetsConfig.load_from_files(
    [Path("topology.toml"), Path("topology-overrides.toml")]
)
relations = config.find_relations(
    microgrid_id=241,
    at=datetime(2026, 1, 15, tzinfo=timezone.utc),
)
```

Later files override individual fields from earlier files. The projections
`find_delivery_areas`, `find_market_locations` and `find_microgrids` accept
filters for the other relation sides and an instant. `find_delivery_areas`
returns each area with its code and code type; a delivery-area filter takes
either a bare code or a full delivery area matched on its code type.

Market locations are keyed by raw ID, so the same raw ID cannot be used in
several market areas within one document.

## Supported Platforms

The following platforms are officially supported (tested):

- **Python:** 3.11
- **Operating System:** Ubuntu Linux 20.04
- **Architectures:** amd64, arm64

## CLI

This package ships the `gridpool-cli` command with five subcommands.

### Setup

Set the Assets API credentials before running the CLI:

```bash
export ASSETS_API_URL="grpc://..."
export ASSETS_API_AUTH_KEY="..."
export ASSETS_API_SIGN_SECRET="..."
```

`FREQUENZ_API_KEY` and `FREQUENZ_API_SECRET` are accepted as fallbacks for
`ASSETS_API_AUTH_KEY` and `ASSETS_API_SIGN_SECRET`.

### Print component formulas

```bash
gridpool-cli print-formulas <microgrid_id>
```

Optional prefix formatting:

```bash
gridpool-cli print-formulas <microgrid_id> --prefix "{microgrid_id}.{component}"
```

The per-category formulas (`pv`, `battery`, `chp`, `ev`) read the component
first and use the meter as the fallback. Use
`--prefer-meters-in-component-formulas` for the opposite order, which is what
versions before component graph v0.5.0 produced:

```bash
gridpool-cli print-formulas <microgrid_id> --prefer-meters-in-component-formulas
```

### Render component graph

Rendering requires optional dependencies. Install with:

```bash
pip install frequenz-gridpool[render-graph]
```

```bash
gridpool-cli render-graph <microgrid_id>
```

To save without opening a window:

```bash
gridpool-cli render-graph <microgrid_id> --no-show --output component_graph.png
```

### Generate microgrid config

Derive metadata, formulas and component IDs for one or more microgrids from the
Assets API and print them as dotted-key TOML to stdout:

```bash
gridpool-cli generate-config <microgrid_id> [<microgrid_id> ...]
```

Redirect stdout to save the result:

```bash
gridpool-cli generate-config <microgrid_id> > microgrid.toml
```

This command emits only microgrid entries. Topology relations, including their
delivery-area codes, and market-location entries from input files are not
included in its stdout output.

You can layer existing microgrid config files with the Assets API by precedence
(`--default` < Assets API < `--override`). Values from a `--default` file are
overridden by the API, while a `--override` file keeps its own values and the
API only fills the gaps:

```bash
gridpool-cli generate-config <microgrid_id> \
    --default defaults.toml \
    --override overrides.toml > microgrid.toml
```

If no microgrid IDs are given, they are taken from the microgrid entries in the
supplied files:

```bash
gridpool-cli generate-config --override existing.toml > microgrid.toml
```

`--prefer-meters-in-component-formulas` works here too, so a regenerated
config can keep the meter-first order of the per-category formulas:

```bash
gridpool-cli generate-config <microgrid_id> \
    --prefer-meters-in-component-formulas > microgrid.toml
```

### Validate config files

Check config files offline, without contacting the Assets API, and exit
non-zero on the first error, to gate config-repo CI:

```bash
gridpool-cli validate microgrid.toml [more.toml ...]
```

Each file is validated on its own first, so every record names its own key and
required fields; the files are then validated merged, for the cross-record
checks.

### Look up a gridpool's enterprise

Print the enterprise ID that owns a gridpool, read from the config files
(merged as one stack); exits non-zero if the gridpool is not declared:

```bash
gridpool-cli find-enterprise <gridpool_id> config.toml [more.toml ...]
```

## Contributing

If you want to know how to build this project and contribute to it, please
check out the [Contributing Guide](CONTRIBUTING.md).
