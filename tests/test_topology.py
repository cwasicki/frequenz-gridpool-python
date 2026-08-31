# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Tests for the market topology relations."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from frequenz.client.assets import (
    EnergyMarketCodeType,
    MarketLocationIdType,
    MarketParticipationType,
)

from frequenz.gridpool.config import (
    AssetsConfig,
    DeliveryAreaConfig,
    RelationConfig,
    ValidityConfig,
)
from frequenz.gridpool.config._topology import _relation_key

_AREA_A = "10YDE-RWENET---I"
_AREA_B = "10YDE-EON------1"

_TOML = """
assets.relations.G80M241L10208446344.gridpool_id = 80
assets.relations.G80M241L10208446344.microgrid_id = 241
assets.relations.G80M241L10208446344.market_location_id = "10208446344"
assets.relations.G80M241L10208446344.delivery_area.code = "10YDE-RWENET---I"

assets.relations.G80L51171875559.gridpool_id = 80
assets.relations.G80L51171875559.market_location_id = "51171875559"
assets.relations.G80L51171875559.delivery_area.code = "10YDE-EON------1"

assets.relations.M217L33333333333.microgrid_id = 217
assets.relations.M217L33333333333.market_location_id = "33333333333"
"""


def _dt(year: int, month: int, day: int) -> datetime:
    """Build a UTC instant at midnight."""
    return datetime(year, month, day, tzinfo=timezone.utc)


def _codes(areas: Any) -> list[str | None]:
    """Take the codes of a list of delivery areas."""
    return [area.code for area in areas]


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
            _relation_key(
                record.get("gridpool_id"),
                record.get("microgrid_id"),
                record.get("market_location_id"),
            ): record
            for record in records
        }
    }


def test_relation_key() -> None:
    """The key names the sides a relation connects, in a fixed order."""
    assert _relation_key(80, 241, "10208446344") == "G80M241L10208446344"
    assert _relation_key(80, market_location_id="5117") == "G80L5117"
    assert _relation_key(microgrid_id=217, market_location_id="333") == "M217L333"


def test_load_relations(tmp_path: Path) -> None:
    """A record states its own sides, and its key clusters its lines."""
    config = AssetsConfig.load_from_files(_write(tmp_path, "relations.toml", _TOML))

    assert len(config.relations) == 3

    relation = config.relations["G80M241L10208446344"]
    assert relation.gridpool_id == 80
    assert relation.microgrid_id == 241
    assert relation.market_location_id == "10208446344"
    assert relation.delivery_area is not None
    assert relation.delivery_area.code == "10YDE-RWENET---I"
    assert relation.delivery_area.code_type is EnergyMarketCodeType.EUROPE_EIC


def test_find_relations(tmp_path: Path) -> None:
    """Relations are searchable by any combination of their sides."""
    config = AssetsConfig.load_from_files(_write(tmp_path, "relations.toml", _TOML))

    assert [r.market_location_id for r in config.find_relations(gridpool_id=80)] == [
        "10208446344",
        "51171875559",
    ]
    assert config.find_relations(microgrid_id=241) == [
        config.relations["G80M241L10208446344"]
    ]
    assert not config.find_relations(gridpool_id=68)


def test_at_least_two_sides_required() -> None:
    """A relation names at least two of gridpool, microgrid, market location."""
    with pytest.raises(ValueError, match="at least two"):
        _load(relations={"G80": {"gridpool_id": 80}})

    with pytest.raises(ValueError, match="at least two"):
        _load(relations={"M241": {"microgrid_id": 241}})


def test_metering_relation_maps_delivery_area_without_gridpool() -> None:
    """A metering relation can map a market location without a gridpool."""
    config = _load(
        **_relations(
            {
                "microgrid_id": 217,
                "market_location_id": "33333333333",
                "delivery_area": {"code": _AREA_A},
            }
        )
    )

    relation = config.relations["M217L33333333333"]
    assert relation.gridpool_id is None
    assert relation.delivery_area is not None
    assert relation.delivery_area.code == _AREA_A
    assert relation.is_complete
    assert relation.covers(_dt(2026, 3, 1))


def test_nothing_is_read_from_the_key() -> None:
    """The key clusters the lines of a record; the values come from its fields."""
    config = AssetsConfig.Schema().load(
        {"relations": {"G80M241L10208446344": {"gridpool_id": 80}}}
    )
    assert isinstance(config, AssetsConfig)

    relation = config.relations["G80M241L10208446344"]
    assert relation.microgrid_id is None
    assert relation.market_location_id is None

    with pytest.raises(ValueError, match="at least two"):
        config.check()


def test_key_must_agree_with_the_fields() -> None:
    """A key that says something else than its record is an error."""
    with pytest.raises(ValueError, match="Relation key mismatch"):
        _load(relations={"G80M241": {"gridpool_id": 80, "microgrid_id": 242}})


def test_gridpool_relation_needs_a_delivery_area() -> None:
    """A relation naming a gridpool must place it in a delivery area."""
    with pytest.raises(ValueError, match="must name a delivery area"):
        _load(**_relations({"gridpool_id": 80, "microgrid_id": 241}))


@pytest.mark.parametrize(
    "delivery_area",
    ["10YDE-RWENET---X", "10YDE-RWENET--I", "10yDE-RWENET---I"],
)
def test_delivery_area_must_be_a_valid_eic(delivery_area: str) -> None:
    """Delivery areas have valid EIC syntax and a matching check character."""
    with pytest.raises(ValueError, match="valid EIC code"):
        _load(
            **_relations(
                {
                    "gridpool_id": 80,
                    "microgrid_id": 241,
                    "delivery_area": {"code": delivery_area},
                }
            )
        )


def test_delivery_area_defaults_to_eic() -> None:
    """A delivery area given as a bare code is read as an EIC code."""
    config = _load(
        **_relations(
            {"gridpool_id": 80, "microgrid_id": 241, "delivery_area": {"code": _AREA_A}}
        )
    )

    area = config.relations["G80M241"].delivery_area
    assert area is not None
    assert area.code == _AREA_A
    assert area.code_type is EnergyMarketCodeType.EUROPE_EIC


def test_delivery_area_can_name_a_non_eic_code_type() -> None:
    """A non-EIC code type is accepted and skips EIC validation."""
    config = _load(
        **_relations(
            {
                "gridpool_id": 80,
                "microgrid_id": 241,
                "delivery_area": {"code": "SOME-US-CODE", "code_type": "US_NERC"},
            }
        )
    )

    area = config.relations["G80M241"].delivery_area
    assert area is not None
    assert area.code == "SOME-US-CODE"
    assert area.code_type is EnergyMarketCodeType.US_NERC


def test_unspecified_delivery_area_code_type_rejected() -> None:
    """A delivery area must name a real code type."""
    with pytest.raises(ValueError, match="code type must be specified"):
        _load(
            **_relations(
                {
                    "gridpool_id": 80,
                    "microgrid_id": 241,
                    "delivery_area": {"code": _AREA_A, "code_type": "UNSPECIFIED"},
                }
            )
        )


def test_microgrid_carries_a_delivery_area_without_a_market_location() -> None:
    """A gridpool-to-microgrid relation carries a delivery area of its own."""
    config = _load(
        **_relations(
            {
                "gridpool_id": 80,
                "microgrid_id": 241,
                "delivery_area": {"code": "10YDE-RWENET---I"},
            }
        )
    )

    relation = config.relations["G80M241"]
    assert relation.market_location_id is None
    assert relation.delivery_area is not None
    assert relation.delivery_area.code == "10YDE-RWENET---I"


def test_market_location_in_two_delivery_areas_rejected() -> None:
    """One market location cannot sit in two delivery areas across relations."""
    with pytest.raises(ValueError, match="two delivery areas"):
        _load(
            **_relations(
                {
                    "gridpool_id": 80,
                    "market_location_id": "77777777777",
                    "delivery_area": {"code": "10YDE-RWENET---I"},
                },
                {
                    "gridpool_id": 81,
                    "market_location_id": "77777777777",
                    "delivery_area": {"code": "10YDE-EON------1"},
                },
            )
        )


def test_delivery_area_code_with_two_code_types_rejected() -> None:
    """A delivery-area code is bound to a single code type across relations."""
    with pytest.raises(ValueError, match="two code types"):
        _load(
            **_relations(
                {
                    "gridpool_id": 80,
                    "microgrid_id": 241,
                    "delivery_area": {"code": _AREA_A, "code_type": "EUROPE_EIC"},
                },
                {
                    "gridpool_id": 81,
                    "microgrid_id": 242,
                    "delivery_area": {"code": _AREA_A, "code_type": "US_NERC"},
                },
            )
        )

    _load(
        **_relations(
            {
                "gridpool_id": 80,
                "microgrid_id": 241,
                "delivery_area": {"code": _AREA_A},
            },
            {
                "gridpool_id": 81,
                "microgrid_id": 242,
                "delivery_area": {"code": _AREA_A},
            },
        )
    )


def test_microgrid_in_two_gridpools_by_participation() -> None:
    """One microgrid can take part in two gridpools, told apart by use case."""
    config = _load(
        **_relations(
            {
                "gridpool_id": 80,
                "microgrid_id": 241,
                "delivery_area": {"code": "10YDE-RWENET---I"},
                "validity": {"a": {"participation": "ENERGY_TRADING"}},
            },
            {
                "gridpool_id": 46,
                "microgrid_id": 241,
                "delivery_area": {"code": "10YDE-RWENET---I"},
                "validity": {"a": {"participation": "FLEX_MARKETS"}},
            },
        )
    )

    trading = config.find_relations(
        microgrid_id=241, participation=MarketParticipationType.ENERGY_TRADING
    )
    flex = config.find_relations(
        microgrid_id=241, participation=MarketParticipationType.FLEX_MARKETS
    )
    assert [r.gridpool_id for r in trading] == [80]
    assert [r.gridpool_id for r in flex] == [46]
    assert len(config.find_relations(microgrid_id=241)) == 2


def test_legacy_gridpool_id_must_match_relations() -> None:
    """The legacy scalar gridpool ID must describe all current relations."""
    microgrids = {"241": {"microgrid_id": 241, "gid": 80}}

    config = _load(
        microgrids=microgrids,
        **_relations(
            {"gridpool_id": 80, "microgrid_id": 241, "delivery_area": {"code": _AREA_A}}
        ),
    )
    assert config.microgrids[241].gid == 80

    _load(
        microgrids={"241": {"microgrid_id": 241}},
        **_relations(
            {
                "gridpool_id": 80,
                "microgrid_id": 241,
                "delivery_area": {"code": _AREA_A},
            },
            {
                "gridpool_id": 46,
                "microgrid_id": 241,
                "delivery_area": {"code": _AREA_A},
            },
        ),
    )

    with pytest.raises(ValueError, match="legacy gid"):
        _load(
            microgrids=microgrids,
            **_relations(
                {
                    "gridpool_id": 46,
                    "microgrid_id": 241,
                    "delivery_area": {"code": _AREA_A},
                }
            ),
        )

    with pytest.raises(ValueError, match="remove gid"):
        _load(
            microgrids=microgrids,
            **_relations(
                {
                    "gridpool_id": 80,
                    "microgrid_id": 241,
                    "delivery_area": {"code": _AREA_A},
                },
                {
                    "gridpool_id": 46,
                    "microgrid_id": 241,
                    "delivery_area": {"code": _AREA_A},
                },
            ),
        )


def test_two_use_cases_on_one_relation_may_overlap() -> None:
    """Different use cases can run at once on the same relation."""
    config = _load(
        **_relations(
            {
                "gridpool_id": 80,
                "microgrid_id": 241,
                "delivery_area": {"code": "10YDE-RWENET---I"},
                "validity": {
                    "trading": {"participation": "ENERGY_TRADING"},
                    "flex": {"participation": "FLEX_MARKETS"},
                },
            }
        )
    )

    relation = config.relations["G80M241"]
    assert relation.matches(participation=MarketParticipationType.ENERGY_TRADING)
    assert relation.matches(participation=MarketParticipationType.FLEX_MARKETS)


def test_one_use_case_cannot_overlap_itself() -> None:
    """The same use case cannot apply twice at the same instant."""
    with pytest.raises(ValueError, match="ENERGY_TRADING periods"):
        _load(
            **_relations(
                {
                    "gridpool_id": 80,
                    "microgrid_id": 241,
                    "delivery_area": {"code": "10YDE-RWENET---I"},
                    "validity": {
                        "first": {
                            "participation": "ENERGY_TRADING",
                            "start": _dt(2026, 1, 15),
                            "end": _dt(2026, 6, 30),
                        },
                        "second": {
                            "participation": "ENERGY_TRADING",
                            "start": _dt(2026, 6, 1),
                        },
                    },
                }
            )
        )


def test_market_participation_needs_a_gridpool() -> None:
    """A period naming a market use case applies only in a gridpool context."""
    with pytest.raises(ValueError, match="applies only to a gridpool"):
        _load(
            **_relations(
                {
                    "microgrid_id": 241,
                    "market_location_id": "10208446344",
                    "validity": {"a": {"participation": "ENERGY_TRADING"}},
                }
            )
        )


def test_untyped_period_needs_no_gridpool() -> None:
    """A period without a use case is a plain validity window, gridpool or not."""
    config = _load(
        **_relations(
            {
                "microgrid_id": 217,
                "market_location_id": "33333333333",
                "validity": {
                    "a": {
                        "start": _dt(2026, 1, 15),
                        "end": _dt(2026, 6, 30),
                    }
                },
            }
        )
    )

    relation = config.relations["M217L33333333333"]
    assert relation.gridpool_id is None
    assert relation.covers(_dt(2026, 3, 1))
    assert not relation.covers(_dt(2026, 6, 30))  # end is exclusive
    assert not relation.covers(_dt(2026, 7, 1))
    assert not relation.matches(participation=MarketParticipationType.ENERGY_TRADING)


def test_untyped_periods_cannot_overlap() -> None:
    """Two plain periods of one relation cannot cover the same instant."""
    with pytest.raises(ValueError, match="untyped periods"):
        _load(
            **_relations(
                {
                    "microgrid_id": 217,
                    "market_location_id": "33333333333",
                    "validity": {
                        "first": {
                            "start": _dt(2026, 1, 15),
                            "end": _dt(2026, 6, 30),
                        },
                        "second": {"start": _dt(2026, 6, 1)},
                    },
                }
            )
        )


def test_gridpool_relation_without_participations_always_applies() -> None:
    """A gridpool relation naming no use case is still a relation, applying always."""
    config = _load(
        **_relations(
            {
                "gridpool_id": 80,
                "microgrid_id": 241,
                "delivery_area": {"code": "10YDE-RWENET---I"},
            }
        )
    )

    relation = config.relations["G80M241"]
    assert relation.covers(_dt(2026, 3, 1))
    assert not relation.matches(participation=MarketParticipationType.ENERGY_TRADING)


def test_participation_period() -> None:
    """A relation applies at an instant when a participation covers it."""
    config = _load(
        **_relations(
            {
                "gridpool_id": 80,
                "microgrid_id": 241,
                "delivery_area": {"code": "10YDE-RWENET---I"},
                "validity": {
                    "a": {
                        "participation": "ENERGY_TRADING",
                        "start": _dt(2026, 1, 15),
                        "end": _dt(2026, 6, 30),
                    }
                },
            }
        )
    )

    relation = config.relations["G80M241"]
    assert relation.covers(_dt(2026, 3, 1))
    assert not relation.covers(_dt(2026, 7, 1))
    assert config.find_relations(microgrid_id=241, at=_dt(2026, 3, 1))
    assert not config.find_relations(microgrid_id=241, at=_dt(2026, 7, 1))


def test_inverted_period_rejected() -> None:
    """A participation cannot end before it starts."""
    with pytest.raises(ValueError, match="before it starts"):
        _load(
            **_relations(
                {
                    "gridpool_id": 80,
                    "microgrid_id": 241,
                    "delivery_area": {"code": "10YDE-RWENET---I"},
                    "validity": {
                        "a": {
                            "participation": "ENERGY_TRADING",
                            "start": _dt(2026, 6, 30),
                            "end": _dt(2026, 1, 15),
                        }
                    },
                }
            )
        )


def test_period_and_query_require_a_utc_offset() -> None:
    """Validity bounds and query instants identify absolute instants."""
    naive = datetime(2026, 1, 1)  # noqa: DTZ001

    with pytest.raises(ValueError, match="UTC offset"):
        ValidityConfig(start=naive)

    relation = RelationConfig(microgrid_id=217, market_location_id="33333333333")
    with pytest.raises(ValueError, match="UTC offset"):
        relation.covers(naive)


def test_validity_accepts_datetime_objects_and_iso_strings() -> None:
    """A period loads from native datetimes, as `tomllib` yields, or ISO strings."""
    aware = datetime(2026, 1, 1, tzinfo=timezone.utc)

    from_objects = ValidityConfig.Schema().load(
        {"start": aware, "end": aware.replace(month=6)}
    )
    assert isinstance(from_objects, ValidityConfig)
    assert from_objects.start == aware

    from_strings = ValidityConfig.Schema().load(
        {"start": "2026-01-01T00:00:00+00:00", "end": "2026-06-01T00:00:00+00:00"}
    )
    assert isinstance(from_strings, ValidityConfig)
    assert from_strings.start == aware

    naive = datetime(2026, 1, 1)  # noqa: DTZ001
    with pytest.raises(ValueError, match="UTC offset"):
        ValidityConfig.Schema().load({"start": naive})


def test_market_location_properties() -> None:
    """A location identifies its market and how to read its identifier."""
    config = _load(
        market_locations={
            "51171875559": {
                "id": "51171875559",
                "type": "ZAEHLPUNKT",
                "market_area": 109,
            },
            "10208446344": {"id": "10208446344"},
        }
    )

    assert config.market_locations["51171875559"].id == "51171875559"
    assert (
        config.market_locations["51171875559"].type is MarketLocationIdType.ZAEHLPUNKT
    )
    assert config.market_locations["51171875559"].market_area == 109
    assert config.market_locations["10208446344"].type is MarketLocationIdType.MALO_ID
    assert config.market_locations["10208446344"].market_area == 101

    with pytest.raises(Exception, match="Must be one of"):
        _load(market_locations={"10208446344": {"id": "10208446344", "type": "MALO"}})

    with pytest.raises(ValueError, match="Market area must be specified"):
        _load(market_locations={"10208446344": {"id": "10208446344", "market_area": 0}})


def test_market_location_id_must_agree_with_the_key() -> None:
    """A market location's id must match the key it is filed under."""
    with pytest.raises(ValueError, match="Market location key mismatch"):
        _load(market_locations={"10208446344": {"id": "99999999999"}})


def test_merge_files_into_one_document(tmp_path: Path) -> None:
    """The relations of a gridpool can be spread over several files."""
    first = _write(tmp_path, "first.toml", _TOML)
    second = _write(
        tmp_path,
        "second.toml",
        "assets.relations.G80L44444444444.gridpool_id = 80\n"
        'assets.relations.G80L44444444444.market_location_id = "44444444444"\n'
        'assets.relations.G80L44444444444.delivery_area.code = "10YDE-EON------1"\n',
    )

    assert len(AssetsConfig.load_from_files([first, second]).relations) == 4


def test_override_keeps_untouched_fields(tmp_path: Path) -> None:
    """Overriding one field of a relation leaves the rest as they were."""
    base = _write(
        tmp_path,
        "base.toml",
        "assets.relations.G80L51171875559.gridpool_id = 80\n"
        'assets.relations.G80L51171875559.market_location_id = "51171875559"\n'
        'assets.relations.G80L51171875559.delivery_area.code = "10YDE-EON------1"\n',
    )
    override = _write(
        tmp_path,
        "override.toml",
        'assets.relations.G80L51171875559.delivery_area.code = "10YDE-RWENET---I"\n',
    )

    merged = AssetsConfig.load_from_files([base, override])
    relation = merged.relations["G80L51171875559"]

    assert relation.gridpool_id == 80
    assert relation.market_location_id == "51171875559"
    assert relation.delivery_area is not None
    assert relation.delivery_area.code == "10YDE-RWENET---I"


def test_override_completes_only_after_the_merge(tmp_path: Path) -> None:
    """A file that changes one field is incomplete until it is layered."""
    base = _write(tmp_path, "base.toml", _TOML)
    override = _write(
        tmp_path,
        "override.toml",
        "assets.relations.M217L33333333333.microgrid_id = 217\n",
    )

    with pytest.raises(ValueError, match="at least two"):
        AssetsConfig.load_from_files(override)

    relation = AssetsConfig.load_from_files([base, override]).relations[
        "M217L33333333333"
    ]
    assert relation == RelationConfig(
        microgrid_id=217, market_location_id="33333333333"
    )


def test_delivery_areas_of_a_gridpool() -> None:
    """A gridpool's delivery areas come from the relations that name it."""
    config = _load(
        **_relations(
            {
                "gridpool_id": 80,
                "microgrid_id": 241,
                "delivery_area": {"code": _AREA_A},
            },
            {
                "gridpool_id": 80,
                "market_location_id": "511",
                "delivery_area": {"code": _AREA_B},
            },
            {
                "gridpool_id": 80,
                "microgrid_id": 300,
                "delivery_area": {"code": _AREA_A},
            },
        )
    )

    assert _codes(config.find_delivery_areas(gridpool_id=80)) == [_AREA_A, _AREA_B]
    assert _codes(config.find_delivery_areas(microgrid_id=241)) == [_AREA_A]
    assert config.find_delivery_areas(gridpool_id=68) == []


def test_delivery_areas_honour_the_instant() -> None:
    """A relation that has lapsed drops out of its gridpool's delivery areas."""
    config = _load(
        **_relations(
            {
                "gridpool_id": 80,
                "microgrid_id": 241,
                "delivery_area": {"code": _AREA_A},
            },
            {
                "gridpool_id": 80,
                "microgrid_id": 300,
                "delivery_area": {"code": _AREA_B},
                "validity": {"w": {"start": _dt(2026, 1, 1), "end": _dt(2026, 6, 1)}},
            },
        )
    )

    assert _codes(config.find_delivery_areas(gridpool_id=80, at=_dt(2026, 3, 1))) == [
        _AREA_A,
        _AREA_B,
    ]
    assert _codes(config.find_delivery_areas(gridpool_id=80, at=_dt(2026, 9, 1))) == [
        _AREA_A
    ]


def test_market_locations_of_a_microgrid_or_gridpool() -> None:
    """Market locations are searchable by microgrid or by gridpool."""
    config = _load(
        **_relations(
            {
                "gridpool_id": 80,
                "microgrid_id": 241,
                "market_location_id": "111",
                "delivery_area": {"code": _AREA_A},
            },
            {"microgrid_id": 241, "market_location_id": "222"},
            {
                "gridpool_id": 46,
                "microgrid_id": 300,
                "market_location_id": "333",
                "delivery_area": {"code": _AREA_A},
            },
        )
    )

    assert config.find_market_locations(microgrid_id=241) == ["111", "222"]
    assert config.find_market_locations(gridpool_id=80) == ["111"]
    assert config.find_market_locations(microgrid_id=999) == []


def test_find_by_gridpool_and_delivery_area() -> None:
    """Microgrids and market locations narrow to a gridpool's delivery area."""
    config = _load(
        **_relations(
            {
                "gridpool_id": 80,
                "microgrid_id": 241,
                "delivery_area": {"code": _AREA_A},
            },
            {
                "gridpool_id": 80,
                "microgrid_id": 300,
                "market_location_id": "111",
                "delivery_area": {"code": _AREA_A},
            },
            {
                "gridpool_id": 80,
                "market_location_id": "222",
                "delivery_area": {"code": _AREA_A},
            },
            {
                "gridpool_id": 80,
                "market_location_id": "333",
                "delivery_area": {"code": _AREA_B},
            },
        )
    )

    assert config.find_microgrids(gridpool_id=80, delivery_area=_AREA_A) == [241, 300]
    assert config.find_market_locations(gridpool_id=80, delivery_area=_AREA_A) == [
        "111",
        "222",
    ]
    assert config.find_market_locations(gridpool_id=80, delivery_area=_AREA_B) == [
        "333"
    ]


def test_filter_by_delivery_area_config() -> None:
    """A filter takes a bare code or a full delivery area matched on its type."""
    config = _load(
        **_relations(
            {"gridpool_id": 80, "microgrid_id": 241, "delivery_area": {"code": _AREA_A}}
        )
    )

    assert config.find_microgrids(delivery_area=_AREA_A) == [241]
    assert config.find_microgrids(delivery_area=DeliveryAreaConfig(code=_AREA_A)) == [
        241
    ]
    mismatch = DeliveryAreaConfig(code=_AREA_A, code_type=EnergyMarketCodeType.US_NERC)
    assert config.find_microgrids(delivery_area=mismatch) == []


def test_find_by_market_location() -> None:
    """A market location resolves to its microgrid and its delivery area."""
    config = _load(
        **_relations(
            {
                "gridpool_id": 80,
                "microgrid_id": 241,
                "market_location_id": "111",
                "delivery_area": {"code": _AREA_A},
            }
        )
    )

    assert config.find_microgrids(market_location_id="111") == [241]
    assert _codes(config.find_delivery_areas(market_location_id="111")) == [_AREA_A]
    assert config.find_microgrids(market_location_id="999") == []
