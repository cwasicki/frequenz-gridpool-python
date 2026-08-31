# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Reusable marshmallow fields for config data models."""

from datetime import datetime
from typing import Any

import marshmallow


class TomlAwareDateTime(marshmallow.fields.DateTime):
    """A `DateTime` that also accepts an already-parsed `datetime`.

    marshmallow 3's `DateTime` deserialises only ISO strings, but `tomllib`
    yields native `datetime` objects before the value reaches marshmallow, so
    those inputs must pass through unchanged. marshmallow 4 accepts them itself;
    this keeps both behaving the same.
    """

    def _deserialize(self, value: Any, *args: Any, **kwargs: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        return super()._deserialize(value, *args, **kwargs)


def toml_datetime_metadata() -> dict[str, Any]:
    """Field metadata mapping a TOML-sourced `datetime` to `TomlAwareDateTime`."""
    return {"marshmallow_field": TomlAwareDateTime(allow_none=True)}
