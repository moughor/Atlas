from __future__ import annotations
from dataclasses import dataclass
from urllib.parse import quote, unquote, urlparse
from pathlib import Path

@dataclass(frozen=True, slots=True)
class TextDocument:
    uri: str
    text: str
    version: int
    language_id: str = 'java'
    @property
    def path(self) -> str:
        parsed=urlparse(self.uri)
        if parsed.scheme == 'file': return unquote(parsed.path.lstrip('/') if len(parsed.path)>2 and parsed.path[2]==':' else parsed.path)
        return self.uri
    def offset_at(self, line:int, character:int)->int:
        if line < 0 or character < 0: raise ValueError('position values must be non-negative')
        lines=self.text.splitlines(keepends=True)
        if line >= len(lines): return len(self.text)
        return min(sum(len(x) for x in lines[:line])+character, sum(len(x) for x in lines[:line+1]))
    def position_at(self, offset:int)->tuple[int,int]:
        offset=max(0,min(offset,len(self.text))); before=self.text[:offset]; line=before.count('\n'); last=before.rfind('\n'); return line, offset if last<0 else offset-last-1

class DocumentStore:
    def __init__(self): self._documents: dict[str,TextDocument]={}
    def open(self, uri:str,text:str,version:int=1,language_id:str='java')->TextDocument:
        doc=TextDocument(uri,text,version,language_id); self._documents[uri]=doc; return doc
    def change(self,uri:str,text:str,version:int)->TextDocument:
        old=self.require(uri)
        if version <= old.version: raise ValueError('document version must increase')
        return self.open(uri,text,version,old.language_id)
    def close(self,uri:str)->TextDocument|None: return self._documents.pop(uri,None)
    def get(self,uri:str)->TextDocument|None: return self._documents.get(uri)
    def require(self,uri:str)->TextDocument:
        doc=self.get(uri)
        if doc is None: raise KeyError(uri)
        return doc
    def uris(self)->tuple[str,...]: return tuple(sorted(self._documents))
    def __len__(self): return len(self._documents)

def path_to_uri(path:str|Path)->str:
    return Path(path).resolve().as_uri()
