from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from .types import Type, type_to_dict


def semantic_document_to_dict(value):
    if isinstance(value, Type):
        return type_to_dict(value)
    if is_dataclass(value):
        result = {"kind": value.__class__.__name__}
        for item in fields(value):
            result[item.name] = semantic_document_to_dict(getattr(value, item.name))
        return result
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (tuple, list, frozenset, set)):
        return [semantic_document_to_dict(item) for item in value]
    if isinstance(value, (dict, Mapping, MappingProxyType)):
        return {
            str(key): semantic_document_to_dict(value[key])
            for key in sorted(value, key=str)
        }
    if hasattr(value, "__dict__"):
        return {
            "kind": value.__class__.__name__,
            **{
                key: semantic_document_to_dict(item)
                for key, item in sorted(vars(value).items())
                if not key.startswith("_")
            },
        }
    return value
