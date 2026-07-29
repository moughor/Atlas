from __future__ import annotations
from dataclasses import fields, is_dataclass
from enum import Enum

def semantic_to_dict(value):
    if is_dataclass(value):
        result = {"kind": value.__class__.__name__}
        for field in fields(value):
            result[field.name] = semantic_to_dict(getattr(value, field.name))
        return result
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [semantic_to_dict(item) for item in value]
    if isinstance(value, list):
        return [semantic_to_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: semantic_to_dict(value[key]) for key in sorted(value)}
    return value
