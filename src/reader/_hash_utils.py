"""
Generate stable hashes for Python data objects.
Contains no business logic.

The hashes should be stable across interpreter implementations and versions.

Supports dataclass instances, datetimes, and JSON-serializable objects.

Empty dataclass fields are ignored, to allow adding new fields without
the hash changing. Empty means one of: None, '', (), [], or {}.

The dataclass type is ignored: two instances of different types
will have the same hash if they have the same attribute/value pairs.

Design choices explained in https://death.andgravity.com/stable-hashing

Implemented for https://github.com/lemon24/reader/issues/179

"""
import dataclasses
import datetime
import hashlib
import json
from collections.abc import Collection
from typing import Any
from typing import Dict


# The first byte of the hash contains its version,
# to allow upgrading the implementation without changing existing hashes.
# (In practice, it's likely we'll just let the hash change and update
# the affected objects again; nevertheless, it's good to have the option.)
#
# A previous version recommended using a check_hash(thing, hash) -> bool
# function instead of direct equality checking; it was removed because
# it did not allow objects to cache the hash.

_VERSION = 0
_EXCLUDE = '_hash_exclude_'


def get_hash(thing: object) -> bytes:
    prefix = _VERSION.to_bytes(1, 'big')
    digest = hashlib.md5(_json_dumps(thing).encode('utf-8')).digest()
    return prefix + digest[:-1]


def _json_dumps(thing: object) -> str:
    return json.dumps(
        thing,
        default=_json_default,
        # force formatting-related options to known values
        ensure_ascii=False,
        sort_keys=True,
        indent=None,
        separators=(',', ':'),
    )


def _json_default(thing: object) -> Any:
    try:
        return _dataclass_dict(thing)
    except TypeError:
        pass
    if isinstance(thing, datetime.datetime):
        return thing.isoformat(timespec='microseconds')
    raise TypeError(f"Object of type {type(thing).__name__} is not JSON serializable")


def _dataclass_dict(thing: object) -> Dict[str, Any]:
    # we could have used dataclasses.asdict()
    # with a dict_factory that drops empty values,
    # but asdict() is recursive and we need to intercept and check
    # the _hash_exclude_ of nested dataclasses;
    # this way, json.dumps() does the recursion instead of asdict()

    # raises TypeError for non-dataclasses
    fields = dataclasses.fields(thing)
    # ... but doesn't for dataclass *types*
    if isinstance(thing, type):
        raise TypeError("got type, expected instance")

    exclude = getattr(thing, _EXCLUDE, ())

    rv = {}
    for field in fields:
        if field.name in exclude:
            continue

        value = getattr(thing, field.name)
        if value is None or not value and isinstance(value, Collection):
            continue

        rv[field.name] = value

    return rv
