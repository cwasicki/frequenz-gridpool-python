# License: MIT
# Copyright © 2025 Frequenz Energy-as-a-Service GmbH

"""Patch existing dotted-key TOML files with new microgrid config values.

Unlike `dump_map`, which rebuilds a TOML document from scratch, this module
only adds missing leaves and missing microgrid entries. Values already on
disk always win, so comments, field order and number formatting survive.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit import TOMLDocument

from frequenz.gridpool.config import MicrogridConfig

from ._dump_config import _format_value, _iter_leaves


def patch_file(path: Path, configs: dict[int, MicrogridConfig]) -> str:
    """Patch the TOML file at `path` with any leaves missing from `configs`.

    Args:
        path: Path to the existing TOML file to patch.
        configs: Mapping from microgrid ID to `MicrogridConfig`.

    Returns:
        The patched TOML text; the caller is responsible for writing it back.
    """
    return patch_text(path.read_text(), configs)


def patch_text(original: str, configs: dict[int, MicrogridConfig]) -> str:
    """Patch dotted-key TOML text with any leaves missing from `configs`.

    Args:
        original: The existing TOML text to patch.
        configs: Mapping from microgrid ID to `MicrogridConfig`.

    Returns:
        The patched TOML text.
    """
    doc = tomlkit.parse(original)
    schema = MicrogridConfig.Schema()

    # Leaves needing a whole new sub-table can't be inserted via item assignment
    # without tomlkit falling back to bracket-header syntax, so they are spliced
    # into the rendered text instead.
    orphans: dict[str, list[tuple[list[str], Any]]] = {}

    for microgrid_id, cfg in configs.items():
        mid = str(microgrid_id)
        dumped = schema.dump(cfg)
        assert isinstance(dumped, dict)
        leaves = _iter_leaves([], dumped)
        if not leaves:
            continue

        if mid not in doc:
            _append_new_entry(doc, mid, leaves)
            continue

        for path, value in leaves:
            if _leaf_exists(doc, mid, path):
                continue
            if not _insert_leaf(doc, mid, path, value):
                orphans.setdefault(mid, []).append((path, value))

    text = tomlkit.dumps(doc)
    if orphans:
        text = _splice_orphans(text, orphans)
    return text


def _leaf_exists(doc: TOMLDocument, mid: str, path: list[str]) -> bool:
    """Whether the dotted key `mid.path...` already has a value in `doc`."""
    node: Any = doc
    for key in (mid, *path):
        if not isinstance(node, Mapping) or key not in node:
            return False
        node = node[key]
    return True


def _insert_leaf(doc: TOMLDocument, mid: str, path: list[str], value: Any) -> bool:
    """Insert a leaf directly onto its existing parent table, if there is one.

    Args:
        doc: The document being patched, mutated in place.
        mid: Microgrid ID the leaf belongs to.
        path: Dotted key path under `mid` for the leaf.
        value: The leaf's value.

    Returns:
        `True` if the leaf was inserted, `False` if a whole new sub-table is
        needed instead (left for the caller to handle).
    """
    node: Any = doc
    matched = 0
    for key in (mid, *path[:-1]):
        nxt = node[key] if isinstance(node, Mapping) and key in node else None
        if not isinstance(nxt, Mapping):
            break
        node = nxt
        matched += 1

    full_path = [mid, *path]
    if matched != len(full_path) - 1:
        return False
    node[full_path[-1]] = _format_value(value)
    return True


def _append_new_entry(
    doc: TOMLDocument, mid: str, leaves: list[tuple[list[str], Any]]
) -> None:
    """Append a brand-new microgrid entry at the end of the document.

    Args:
        doc: The document being patched, mutated in place.
        mid: Microgrid ID of the new entry.
        leaves: Flattened `(path, value)` pairs for the new entry, in
            dataclass field order.
    """
    if doc.body:
        doc.add(tomlkit.nl())
    for path, value in leaves:
        doc.append(tomlkit.key([mid, *path]), _format_value(value))


def _render_lines(mid: str, leaves: list[tuple[list[str], Any]]) -> list[str]:
    """Render `(path, value)` leaves as standalone `mid.path = value` lines."""
    tmp = tomlkit.document()
    for path, value in leaves:
        tmp.append(tomlkit.key([mid, *path]), _format_value(value))
    return tomlkit.dumps(tmp).splitlines(keepends=True)


def _splice_orphans(text: str, orphans: dict[str, list[tuple[list[str], Any]]]) -> str:
    """Insert each microgrid's orphaned leaves right after its own last line.

    Args:
        text: The already-rendered document text.
        orphans: Mapping from microgrid ID to its `(path, value)` leaves
            that need a brand-new sub-table.

    Returns:
        `text` with the orphaned leaves inserted.
    """
    lines = text.splitlines(keepends=True)
    for mid, leaves in orphans.items():
        insert_at = _last_line_index_for_mid(lines, mid)
        new_lines = _render_lines(mid, leaves)
        lines[insert_at + 1 : insert_at + 1] = new_lines
    return "".join(lines)


def _last_line_index_for_mid(lines: list[str], mid: str) -> int:
    """Index of the last line belonging to `mid` (its key starts with `mid.`)."""
    prefix = f"{mid}."
    for idx in range(len(lines) - 1, -1, -1):
        if lines[idx].lstrip().startswith(prefix):
            return idx
    raise ValueError(f"No existing line found for microgrid {mid!r}.")
