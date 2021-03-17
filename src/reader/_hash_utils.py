"""
Generate stable hashes for Python data objects.
Contains no business logic.

The hashes should be stable across interpreter implementations and versions.

Supports dataclass instances, datetimes, and JSON-serializable objects.

Empty dataclass fields are ignored, to allow adding new fields without
the hash changing. Empty means one of: None, '', (), [], or {}.

The dataclass type is ignored: two instances of different types
will have the same hash if they have the same attribute/value pairs.

The hash is versioned to allow upgrading the implementation
without changing existing hashes. For this reason,
check_hash() should be used instead of plain equality checking.

Implemented for https://github.com/lemon24/reader/issues/179

"""
import dataclasses
import datetime
import hashlib
import json
from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any
from typing import Dict


_VERSION = 0
_EXCLUDE = '_hash_exclude_'


def get_hash(thing: object) -> bytes:
    prefix = _VERSION.to_bytes(1, 'big')
    digest = hashlib.md5(_json_dumps(thing).encode('utf-8')).digest()
    return prefix + digest[:-1]


def check_hash(thing: object, hash: bytes) -> bool:
    # TODO (but YAGNI): check hash version and length
    return get_hash(thing) == hash


def _json_dumps(thing: object) -> str:
    return json.dumps(
        thing,
        default=_json_default,
        # force formatting-related options to known values
        ensure_ascii=False,
        sort_keys=True,
        indent=0,
        separators=(',', ':'),
    )


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
        if value is None or not value and isinstance(value, (Sequence, Mapping)):
            continue

        rv[field.name] = value

    return rv


def _json_default(thing: object) -> Any:
    try:
        return _dataclass_dict(thing)
    except TypeError:
        pass
    if isinstance(thing, datetime.datetime):
        return thing.isoformat(timespec='microseconds')
    raise TypeError(f"Object of type {type(thing).__name__} is not JSON serializable")
