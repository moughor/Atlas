from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
class FetchType(str,Enum): LAZY='LAZY'; EAGER='EAGER'
class CascadeType(str,Enum): ALL='ALL'; PERSIST='PERSIST'; MERGE='MERGE'; REMOVE='REMOVE'; REFRESH='REFRESH'; DETACH='DETACH'
@dataclass(frozen=True,order=True)
class EntityNode:
    qualified_name:str; table_name:str
@dataclass(frozen=True,order=True)
class RepositoryNode:
    qualified_name:str; entity_name:str; id_type:str='java.lang.Object'
@dataclass(frozen=True,order=True)
class PersistenceRelation:
    owner:str; target:str; field_name:str; kind:str; fetch:FetchType=FetchType.LAZY; cascades:tuple[CascadeType,...]=(); optional:bool=True
@dataclass(frozen=True)
class PersistenceImpact:
    entity:str; related_entities:tuple[str,...]; repositories:tuple[str,...]
