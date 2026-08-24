# License: MIT
# Copyright © 2025 Frequenz Energy-as-a-Service GmbH

"""CLI tool for gridpool functionality."""

import os
import tempfile
from pathlib import Path

import asyncclick as click
from frequenz.client.assets import AssetsApiClient
from frequenz.client.common.microgrid import MicrogridId

from frequenz.gridpool import ComponentGraphConfig, ComponentGraphGenerator
from frequenz.gridpool.cli._dump_config import dump_map
from frequenz.gridpool.cli._patch_config import patch_file
from frequenz.gridpool.cli._render_graph import ComponentGraphRenderer, RenderOptions
from frequenz.gridpool.config import AssetsConfig, load_configs


@click.group()
async def cli() -> None:
    """CLI tool for gridpool functionality."""


def _graph_config(prefer_meters: bool) -> ComponentGraphConfig | None:
    """Build the graph config for `--prefer-meters-in-component-formulas`.

    Returns `None` when the flag is not set, so the component graph library's
    own defaults apply.
    """
    if not prefer_meters:
        return None
    return ComponentGraphConfig(prefer_meters_in_component_formulas=True)


@cli.command()
@click.argument("microgrid_id", type=int)
@click.option(
    "--prefix",
    type=str,
    default="{component}",
    help="Prefix format for the output (Supports {microgrid_id} and {component} placeholders).",
)
@click.option(
    "--prefer-meters-in-component-formulas",
    is_flag=True,
    default=False,
    help="Read the meter before the component in the per-category formulas. "
    "This is the order used before component graph v0.5.0.",
)
async def print_formulas(
    microgrid_id: int,
    prefix: str,
    prefer_meters_in_component_formulas: bool,
) -> None:
    """Fetch and print component graph formulas for a microgrid."""
    url = os.environ.get("ASSETS_API_URL")
    key = os.environ.get("ASSETS_API_AUTH_KEY")
    secret = os.environ.get("ASSETS_API_SIGN_SECRET")
    if not url or not key or not secret:
        raise click.ClickException(
            "ASSETS_API_URL, ASSETS_API_AUTH_KEY, ASSETS_API_SIGN_SECRET must be set."
        )

    async with AssetsApiClient(
        url,
        auth_key=key,
        sign_secret=secret,
    ) as client:
        cgg = ComponentGraphGenerator(
            client, config=_graph_config(prefer_meters_in_component_formulas)
        )

        graph = await cgg.get_component_graph(MicrogridId(microgrid_id))
        power_formulas = {
            "consumption": graph.consumer_formula(),
            "generation": graph.producer_formula(),
            "grid": graph.grid_formula(),
            "pv": graph.pv_formula(None),
            "battery": graph.battery_formula(None),
            "chp": graph.chp_formula(None),
            "ev": graph.ev_charger_formula(None),
        }

        for component, formula in power_formulas.items():
            print(
                prefix.format(component=component, microgrid_id=microgrid_id)
                + f' = "{formula}"'
            )


@cli.command("render-graph")
@click.argument("microgrid_id", type=int)
@click.option(
    "--output",
    type=click.Path(dir_okay=False, writable=True),
    default="component_graph.png",
    show_default=True,
    help="Output image path.",
)
@click.option(
    "--show/--no-show",
    default=True,
    show_default=True,
    help="Display the graph interactively.",
)
async def render_graph(microgrid_id: int, output: str, show: bool) -> None:
    """Render and save a component graph visualization for a microgrid."""
    url = os.environ.get("ASSETS_API_URL")
    key = os.environ.get("ASSETS_API_AUTH_KEY")
    secret = os.environ.get("ASSETS_API_SIGN_SECRET")
    if not url or not key or not secret:
        raise click.ClickException(
            "ASSETS_API_URL, ASSETS_API_AUTH_KEY, ASSETS_API_SIGN_SECRET must be set."
        )

    try:
        async with AssetsApiClient(
            url,
            auth_key=key,
            sign_secret=secret,
        ) as client:
            renderer = ComponentGraphRenderer(client)
            graph = await renderer.build_graph(MicrogridId(microgrid_id))
            if not graph.nodes:
                raise click.ClickException("No components found for this microgrid.")
            pos = renderer.compute_layout(graph)
            renderer.render(graph, pos, RenderOptions(output=output, show=show))
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc


@cli.command("generate-config")
@click.argument("microgrid_ids", type=int, nargs=-1)
@click.option(
    "--default",
    "default_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Config file whose values the Assets API overrides (lowest precedence).",
)
@click.option(
    "--override",
    "override_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Config file whose values override the Assets API (highest precedence).",
)
@click.option(
    "--inplace",
    is_flag=True,
    default=False,
    help="Patch --default in place instead of printing to stdout. Preserves "
    "existing comments, ordering and formatting in that file; only fills in "
    "values it is missing. Requires --default.",
)
@click.option(
    "--prefer-meters-in-component-formulas",
    is_flag=True,
    default=False,
    help="Read the meter before the component in the per-category formulas. "
    "This is the order used before component graph v0.5.0.",
)
async def generate_config(
    microgrid_ids: tuple[int, ...],
    default_file: Path | None,
    override_file: Path | None,
    inplace: bool,
    prefer_meters_in_component_formulas: bool,
) -> None:
    """Generate microgrid config from the Assets API as TOML.

    Derives metadata, formulas and component IDs for the given microgrid IDs and
    prints the result as dotted-key TOML to stdout.

    `--default` and `--override` each take a config file, layered with the Assets
    API by precedence: `--default` < Assets API < `--override`. If no microgrid
    IDs are given, they are taken from the supplied files. Files are only read;
    redirect stdout to save the result.

    With `--prefer-meters-in-component-formulas`, the per-category formulas
    read the meter before the component, which is the order used before
    component graph v0.5.0.

    With `--inplace`, `--default` is patched directly instead: candidate values
    come from the Assets API (with `--override` layered on top), and only
    leaves `--default` is missing are added, preserving its existing comments,
    field order and formatting. If no microgrid IDs are given, every microgrid
    already in `--default` is processed.
    """
    if inplace and default_file is None:
        raise click.ClickException("--inplace requires --default.")

    url = os.environ.get("ASSETS_API_URL")
    key = os.environ.get("ASSETS_API_AUTH_KEY")
    secret = os.environ.get("ASSETS_API_SIGN_SECRET")
    if not url or not key or not secret:
        raise click.ClickException(
            "ASSETS_API_URL, ASSETS_API_AUTH_KEY, ASSETS_API_SIGN_SECRET must be set."
        )

    ids = list(dict.fromkeys(microgrid_ids)) or None
    if inplace and ids is None:
        assert default_file is not None
        ids = sorted(AssetsConfig.load_from_files(default_file).microgrids)

    async with AssetsApiClient(url, auth_key=key, sign_secret=secret) as client:
        if inplace:
            # default_file is the patch target here, not a merge input.
            configs = (
                await load_configs(
                    assets_client=client,
                    override_files=override_file,
                    microgrid_ids=ids,
                    component_graph_config=_graph_config(
                        prefer_meters_in_component_formulas
                    ),
                )
            ).microgrids
        else:
            configs = (
                await load_configs(
                    default_files=default_file,
                    assets_client=client,
                    override_files=override_file,
                    microgrid_ids=ids,
                    component_graph_config=_graph_config(
                        prefer_meters_in_component_formulas
                    ),
                )
            ).microgrids

    if not configs:
        raise click.ClickException("No microgrids could be loaded; nothing to write.")

    if inplace:
        assert default_file is not None
        patched = patch_file(default_file, configs)
        fd, tmp_name = tempfile.mkstemp(
            dir=default_file.parent, prefix=f".{default_file.name}."
        )
        try:
            with os.fdopen(fd, "w") as tmp_file:
                tmp_file.write(patched)
            os.replace(tmp_name, default_file)
        except BaseException:
            os.remove(tmp_name)
            raise
        click.echo(f"Patched {default_file}", err=True)
    else:
        click.echo(dump_map(configs), nl=False)


def main() -> None:
    """Run the CLI tool."""
    cli(_anyio_backend="asyncio")


if __name__ == "__main__":
    main()
