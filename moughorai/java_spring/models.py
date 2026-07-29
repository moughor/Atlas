"""Immutable Spring semantic analysis models."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

class SpringBeanKind(str, Enum):
    COMPONENT = "component"
    SERVICE = "service"
    REPOSITORY = "repository"
    CONTROLLER = "controller"
    REST_CONTROLLER = "rest_controller"
    CONFIGURATION = "configuration"

class InjectionKind(str, Enum):
    CONSTRUCTOR = "constructor"
    FIELD = "field"

@dataclass(frozen=True)
class SpringBean:
    qualified_name: str
    kind: SpringBeanKind
    annotations: tuple[str, ...]
    source: Path | None = None

@dataclass(frozen=True)
class InjectionPoint:
    owner: str
    target_name: str
    target_qualified_name: str | None
    kind: InjectionKind
    member_name: str
    required: bool = True

@dataclass(frozen=True)
class SpringEndpoint:
    owner: str
    method_name: str
    http_methods: tuple[str, ...]
    annotations: tuple[str, ...]
    paths: tuple[str, ...] = ()

@dataclass(frozen=True)
class SpringAnalysisReport:
    beans: tuple[SpringBean, ...] = ()
    injections: tuple[InjectionPoint, ...] = ()
    endpoints: tuple[SpringEndpoint, ...] = ()

    def bean(self, qualified_name: str) -> SpringBean | None:
        return next((bean for bean in self.beans if bean.qualified_name == qualified_name), None)

    def dependencies(self, owner: str) -> tuple[InjectionPoint, ...]:
        return tuple(point for point in self.injections if point.owner == owner)

    def dependents(self, target: str) -> tuple[InjectionPoint, ...]:
        return tuple(point for point in self.injections if point.target_qualified_name == target)

    def endpoints_for(self, owner: str) -> tuple[SpringEndpoint, ...]:
        return tuple(endpoint for endpoint in self.endpoints if endpoint.owner == owner)
