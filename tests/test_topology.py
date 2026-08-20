# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Tests for the market topology entities and their relations."""

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from frequenz.client.assets import MarketLocationIdType

from frequenz.gridpool.config import (
    AssetsConfig,
    RelationConfig,
    load_assets_from_files,
    relation_key,
)

_TOML = """
assets.market_locations.10208446344.delivery_area = "10YDE-RWENET---I"
assets.market_locations.51171875559.delivery_area = "10YDE-RWENET---I"

assets.relations.e80g80m241l10208446344.enterprise_id = 80
assets.relations.e80g80m241l10208446344.gridpool_id = 80
assets.relations.e80g80m241l10208446344.microgrid_id = 241
assets.relations.e80g80m241l10208446344.market_location_id = "10208446344"

assets.relations.e80g80l51171875559.enterprise_id = 80
assets.relations.e80g80l51171875559.gridpool_id = 80
assets.relations.e80g80l51171875559.market_location_id = "51171875559"

assets.relations.e73g68m217.enterprise_id = 73
assets.relations.e73g68m217.gridpool_id = 68
assets.relations.e73g68m217.microgrid_id = 217
"""


def _write(tmp_path: Path, name: str, content: str) -> Path:
    """Write a config file and return its path."""
    path = tmp_path / name
    path.write_text(content)
    return path


def _load(**tables: Any) -> AssetsConfig:
    """Load a document straight from its tables and check it as a whole."""
    loaded = AssetsConfig.Schema().load(tables)
    assert isinstance(loaded, AssetsConfig)
    loaded.check()
    return loaded


def _relations(*records: dict[str, Any]) -> dict[str, Any]:
    """Build a relation table, each record filed under its own key."""
    return {
        "relations": {
            relation_key(
                record.get("enterprise_id"),
                record.get("gridpool_id"),
                record.get("microgrid_id"),
                record.get("market_location_id"),
            ): record
            for record in records
        }
    }


def test_relation_key() -> None:
    """The key names the sides a relation connects, in a fixed order."""
    assert relation_key(80, 80, 241, "10208446344") == "e80g80m241l10208446344"
    assert relation_key(80, 80, market_location_id="5117") == "e80g80l5117"
    assert relation_key(73, 68, 217) == "e73g68m217"
    assert relation_key(10, microgrid_id=999) == "e10m999"


def test_load_relations(tmp_path: Path) -> None:
    """A record states its own sides, and its key clusters its lines."""
    config = AssetsConfig.load_from_file(_write(tmp_path, "relations.toml", _TOML))

    assert len(config.relations) == 3

    relation = config.relations["e80g80m241l10208446344"]
    assert relation.enterprise_id == 80
    assert relation.gridpool_id == 80
    assert relation.microgrid_id == 241
    assert relation.market_location_id == "10208446344"
    assert not relation.is_ownership
    assert config.delivery_area(relation) == "10YDE-RWENET---I"


def test_find_relations(tmp_path: Path) -> None:
    """Relations are searchable by any combination of their sides."""
    config = AssetsConfig.load_from_file(_write(tmp_path, "relations.toml", _TOML))

    assert [r.market_location_id for r in config.find_relations(gridpool_id=80)] == [
        "10208446344",
        "51171875559",
    ]
    assert config.find_relations(microgrid_id=241) == [
        config.relations["e80g80m241l10208446344"]
    ]
    assert not config.find_relations(gridpool_id=68, microgrid_id=241)
    assert len(config.find_relations(enterprise_id=80)) == 2


def test_ownership_records_are_left_out_by_default() -> None:
    """A record naming a single asset only says who owns it."""
    config = _load(
        **_relations(
            {"enterprise_id": 10, "microgrid_id": 999},
            {"enterprise_id": 10, "gridpool_id": 10, "microgrid_id": 999},
        )
    )

    assert config.relations["e10m999"].is_ownership
    assert [r.key for r in config.find_relations(microgrid_id=999)] == ["e10g10m999"]
    assert [r.key for r in config.find_relations(microgrid_id=999, ownership=True)] == [
        "e10m999"
    ]
    assert len(config.find_relations(microgrid_id=999, ownership=None)) == 2


def test_incomplete_records_are_rejected() -> None:
    """A relation names an enterprise and at least one asset."""
    with pytest.raises(ValueError, match="must name an enterprise"):
        _load(relations={"e80": {"enterprise_id": 80}})

    with pytest.raises(ValueError, match="must name an enterprise"):
        _load(relations={"e80g80m241": {"gridpool_id": 80, "microgrid_id": 241}})


def test_nothing_is_read_from_the_key() -> None:
    """The key clusters the lines of a record; the values come from its fields."""
    config = AssetsConfig.Schema().load(
        {"relations": {"e80g80m241l10208446344": {"enterprise_id": 80}}}
    )
    assert isinstance(config, AssetsConfig)

    relation = config.relations["e80g80m241l10208446344"]
    assert relation.gridpool_id is None
    assert relation.microgrid_id is None

    with pytest.raises(ValueError, match="must name an enterprise"):
        config.check()


def test_key_must_agree_with_the_fields() -> None:
    """A key that says something else than its record is an error."""
    with pytest.raises(ValueError, match="Relation key mismatch"):
        _load(
            relations={
                "e80g80m241": {
                    "enterprise_id": 80,
                    "gridpool_id": 80,
                    "microgrid_id": 242,
                }
            }
        )


def test_delivery_area_from_the_entities() -> None:
    """The zone sits on the connection point, on the malo or on the microgrid."""
    config = _load(
        market_locations={"10208446344": {"delivery_area": "10YDE-RWENET---I"}},
        microgrids={
            "242": {"meta": {"microgrid_id": 242, "delivery_area": "10YDE-EON------1"}}
        },
        **_relations(
            {
                "enterprise_id": 80,
                "microgrid_id": 241,
                "market_location_id": "10208446344",
            },
            {"enterprise_id": 80, "gridpool_id": 80, "microgrid_id": 242},
        ),
    )

    areas = {r.key: config.delivery_area(r) for r in config.find_relations()}
    assert areas == {
        "e80m241l10208446344": "10YDE-RWENET---I",
        "e80g80m242": "10YDE-EON------1",
    }


def test_relation_without_a_known_area() -> None:
    """A relation whose entities say nothing about the zone still loads."""
    config = _load(
        **_relations({"enterprise_id": 80, "gridpool_id": 80, "microgrid_id": 241})
    )

    assert config.delivery_area(config.relations["e80g80m241"]) is None


def test_one_owner_per_asset_at_a_time() -> None:
    """Two enterprises cannot hold the same asset on the same day."""
    with pytest.raises(ValueError, match="owns the same asset"):
        _load(
            **_relations(
                {"enterprise_id": 10, "microgrid_id": 999},
                {"enterprise_id": 44, "microgrid_id": 999},
            )
        )


def test_owner_may_change_between_periods() -> None:
    """A transfer is one record ending and another starting."""
    config = _load(
        **_relations(
            {"enterprise_id": 10, "microgrid_id": 999, "end": date(2026, 2, 28)},
            {"enterprise_id": 44, "microgrid_id": 999, "start": date(2026, 3, 1)},
        )
    )

    def owner_at(day: date) -> list[int | None]:
        return [
            r.enterprise_id
            for r in config.find_relations(microgrid_id=999, at=day, ownership=True)
        ]

    assert owner_at(date(2026, 1, 1)) == [10]
    assert owner_at(date(2026, 6, 1)) == [44]


def test_flat_period() -> None:
    """A relation with `start` and `end` applies only between them."""
    config = _load(
        **_relations(
            {
                "enterprise_id": 80,
                "gridpool_id": 80,
                "microgrid_id": 241,
                "start": date(2026, 1, 15),
                "end": date(2026, 6, 30),
            }
        )
    )

    relation = config.relations["e80g80m241"]
    assert relation.covers(date(2026, 3, 1))
    assert not relation.covers(date(2026, 7, 1))


def test_undated_relation_always_applies() -> None:
    """Without any dates a relation covers every day, as all of them do today."""
    config = _load(
        **_relations({"enterprise_id": 80, "gridpool_id": 80, "microgrid_id": 241})
    )

    assert config.relations["e80g80m241"].covers(date(2026, 3, 1))


def test_validity_labels_are_not_read() -> None:
    """Labels only name a period; the dates come from the fields."""
    config = _load(
        **_relations(
            {
                "enterprise_id": 80,
                "gridpool_id": 80,
                "microgrid_id": 241,
                "validity": {
                    "metering_issue": {"start": date(2026, 9, 1)},
                    "2026-01-15": {
                        "start": date(2026, 1, 15),
                        "end": date(2026, 6, 30),
                    },
                },
            }
        )
    )

    relation = config.relations["e80g80m241"]
    assert [p.start for p in relation.periods] == [date(2026, 1, 15), date(2026, 9, 1)]
    assert relation.covers(date(2026, 10, 1))
    assert not relation.covers(date(2026, 7, 15))


def test_both_period_forms_rejected() -> None:
    """`validity` replaces the flat fields rather than adding to them."""
    with pytest.raises(ValueError, match="replaces `start` and `end`"):
        _load(
            **_relations(
                {
                    "enterprise_id": 80,
                    "gridpool_id": 80,
                    "microgrid_id": 241,
                    "start": date(2026, 1, 15),
                    "validity": {"a": {"start": date(2026, 9, 1)}},
                }
            )
        )


def test_overlapping_periods_rejected() -> None:
    """A relation cannot apply twice on the same day."""
    with pytest.raises(ValueError, match="overlap"):
        _load(
            **_relations(
                {
                    "enterprise_id": 80,
                    "gridpool_id": 80,
                    "microgrid_id": 241,
                    "validity": {
                        "first": {"start": date(2026, 1, 15), "end": date(2026, 6, 30)},
                        "second": {"start": date(2026, 6, 1)},
                    },
                }
            )
        )


def test_inverted_period_rejected() -> None:
    """A period cannot end before it starts."""
    with pytest.raises(ValueError, match="before it starts"):
        _load(
            **_relations(
                {
                    "enterprise_id": 80,
                    "gridpool_id": 80,
                    "microgrid_id": 241,
                    "start": date(2026, 6, 30),
                    "end": date(2026, 1, 15),
                }
            )
        )


def test_market_location_type() -> None:
    """A location says how to read its identifier, defaulting to a German malo."""
    config = _load(market_locations={"51171875559": {"type": "ZAEHLPUNKT"}})

    assert config.market_location("51171875559").type is MarketLocationIdType.ZAEHLPUNKT
    assert config.market_location("10208446344").type is MarketLocationIdType.MALO_ID

    with pytest.raises(Exception, match="Must be one of"):
        _load(market_locations={"10208446344": {"type": "MALO"}})


def test_merge_files_into_one_document(tmp_path: Path) -> None:
    """The relations of a gridpool can be spread over several files."""
    first = _write(tmp_path, "first.toml", _TOML)
    second = _write(
        tmp_path,
        "second.toml",
        "assets.relations.e80g80l44444444444.enterprise_id = 80\n"
        "assets.relations.e80g80l44444444444.gridpool_id = 80\n"
        'assets.relations.e80g80l44444444444.market_location_id = "44444444444"\n',
    )

    assert len(load_assets_from_files([first, second]).relations) == 4


def test_override_completes_only_after_the_merge(tmp_path: Path) -> None:
    """A file that changes one field is incomplete until it is layered."""
    base = _write(tmp_path, "base.toml", _TOML)
    override = _write(
        tmp_path,
        "override.toml",
        "assets.relations.e73g68m217.end = 2026-06-30\n",
    )

    with pytest.raises(ValueError, match="must name an enterprise"):
        AssetsConfig.load_from_file(override)

    relation = load_assets_from_files([base, override]).relations["e73g68m217"]

    assert relation.microgrid_id == 217
    assert relation.end == date(2026, 6, 30)


def test_merge_checks_the_result(tmp_path: Path) -> None:
    """Each file is fine alone, and their contradiction only shows once merged."""
    first = _write(
        tmp_path,
        "first.toml",
        "assets.relations.e10m999.enterprise_id = 10\n"
        "assets.relations.e10m999.microgrid_id = 999\n",
    )
    second = _write(
        tmp_path,
        "second.toml",
        "assets.relations.e44m999.enterprise_id = 44\n"
        "assets.relations.e44m999.microgrid_id = 999\n",
    )

    AssetsConfig.load_from_file(first)
    AssetsConfig.load_from_file(second)

    with pytest.raises(ValueError, match="owns the same asset"):
        load_assets_from_files([first, second])


def test_relations_need_no_entity_entries() -> None:
    """Relations name entities that other files, or nothing at all, describe."""
    config = _load(
        **_relations({"enterprise_id": 80, "gridpool_id": 80, "microgrid_id": 241})
    )

    assert not config.microgrids
    assert config.relations["e80g80m241"] == RelationConfig(
        enterprise_id=80, gridpool_id=80, microgrid_id=241
    )
