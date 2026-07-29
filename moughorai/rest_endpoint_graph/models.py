from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

class HttpMethod(str, Enum):
    GET='GET'; POST='POST'; PUT='PUT'; PATCH='PATCH'; DELETE='DELETE'; OPTIONS='OPTIONS'; HEAD='HEAD'; ANY='ANY'

@dataclass(frozen=True, order=True)
class RestEndpoint:
    owner: str
    method_name: str
    http_method: HttpMethod
    path: str
    consumes: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    source_symbol: str | None = None

@dataclass(frozen=True, order=True)
class EndpointCall:
    endpoint_key: str
    target_symbol: str

@dataclass(frozen=True)
class EndpointConflict:
    http_method: HttpMethod
    path: str
    endpoint_keys: tuple[str, ...]
