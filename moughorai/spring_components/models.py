from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

class ComponentKind(str, Enum):
    COMPONENT='component'; SERVICE='service'; REPOSITORY='repository'; CONTROLLER='controller'; REST_CONTROLLER='rest_controller'; CONFIGURATION='configuration'; BEAN_METHOD='bean_method'

@dataclass(frozen=True)
class ComponentDefinition:
    qualified_name:str
    kind:ComponentKind
    bean_name:str
    exposed_types:tuple[str,...]=()
    qualifiers:tuple[str,...]=()
    primary:bool=False
    source:Path|None=None
    factory_owner:str|None=None
    factory_method:str|None=None

@dataclass(frozen=True)
class ComponentCatalog:
    components:tuple[ComponentDefinition,...]=()
    def by_name(self,name:str)->tuple[ComponentDefinition,...]:
        return tuple(c for c in self.components if c.bean_name==name)
    def by_type(self,type_name:str)->tuple[ComponentDefinition,...]:
        return tuple(c for c in self.components if type_name==c.qualified_name or type_name in c.exposed_types)
    def primary_for(self,type_name:str)->ComponentDefinition|None:
        matches=tuple(c for c in self.by_type(type_name) if c.primary)
        return matches[0] if len(matches)==1 else None
