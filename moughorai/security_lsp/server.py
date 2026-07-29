from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, unquote
from moughorai.java_security import JavaSecurityAnalyzer
from .adapter import diagnostics_for_findings
from .documents import DocumentStore
from .models import CodeAction, Diagnostic, Position, PublishDiagnostics, Range
from .symbols import document_symbols

@dataclass(frozen=True, slots=True)
class ServerCapabilities:
    text_document_sync: int = 1
    code_action_provider: bool = True
    document_symbol_provider: bool = True
    workspace_symbol_provider: bool = True
    def to_dict(self): return {'textDocumentSync':self.text_document_sync,'codeActionProvider':self.code_action_provider,'documentSymbolProvider':self.document_symbol_provider,'workspaceSymbolProvider':self.workspace_symbol_provider}

class SecurityLanguageServer:
    def __init__(self, analyzer:JavaSecurityAnalyzer|None=None):
        self.analyzer=analyzer or JavaSecurityAnalyzer(); self.documents=DocumentStore(); self.root_uri=None; self.initialized=False; self.shutdown_requested=False; self._published:dict[str,PublishDiagnostics]={}
    def initialize(self,root_uri:str|None=None)->dict[str,Any]:
        self.root_uri=root_uri; self.initialized=True
        return {'capabilities':ServerCapabilities().to_dict(),'serverInfo':{'name':'Atlas Security LSP','version':'0.44'}}
    def shutdown(self): self.shutdown_requested=True; return None
    def did_open(self,uri:str,text:str,version:int=1,language_id:str='java')->PublishDiagnostics:
        doc=self.documents.open(uri,text,version,language_id); return self._analyze(doc.uri)
    def did_change(self,uri:str,text:str,version:int)->PublishDiagnostics:
        doc=self.documents.change(uri,text,version); return self._analyze(doc.uri)
    def did_save(self,uri:str,text:str|None=None)->PublishDiagnostics:
        if text is not None:
            old=self.documents.require(uri); self.documents.open(uri,text,old.version,old.language_id)
        return self._analyze(uri)
    def did_close(self,uri:str)->PublishDiagnostics:
        self.documents.close(uri); result=PublishDiagnostics(uri,None,()); self._published[uri]=result; return result
    def diagnostics(self,uri:str)->tuple[Diagnostic,...]: return self._published.get(uri,PublishDiagnostics(uri,None,())).diagnostics
    def _analyze(self,uri:str)->PublishDiagnostics:
        doc=self.documents.require(uri)
        if doc.language_id != 'java' and not uri.lower().endswith('.java'): diagnostics=()
        else:
            report=self.analyzer.analyze_source(doc.text,doc.path or 'Source.java'); diagnostics=diagnostics_for_findings(report.findings,doc.text)
        result=PublishDiagnostics(uri,doc.version,diagnostics); self._published[uri]=result; return result
    def document_symbols(self,uri:str): return document_symbols(self.documents.require(uri).text)
    def workspace_symbols(self,query:str=''):
        q=query.casefold(); out=[]
        for uri in self.documents.uris():
            for symbol in self.document_symbols(uri):
                if not q or q in symbol.name.casefold(): out.append({'name':symbol.name,'kind':symbol.kind,'location':{'uri':uri,'range':symbol.selection_range.to_dict()}})
        return tuple(sorted(out,key=lambda x:(x['name'].casefold(),x['location']['uri'])))
    def code_actions(self,uri:str,diagnostics:tuple[Diagnostic,...]|None=None)->tuple[CodeAction,...]:
        selected=diagnostics if diagnostics is not None else self.diagnostics(uri); actions=[]
        for d in selected:
            actions.append(CodeAction(f'Suppress {d.code}','quickfix',(d,),command='atlas.suppressFinding',data=(('uri',uri),('code',d.code),('line',d.range.start.line))))
            actions.append(CodeAction(f'Explain {d.code}','quickfix',(d,),command='atlas.explainFinding',data=(('code',d.code),)))
        if selected: actions.append(CodeAction('Rescan document','source',selected,command='atlas.rescanDocument',data=(('uri',uri),)))
        return tuple(sorted(actions,key=lambda a:(a.title,a.kind)))
    def execute_command(self,command:str,arguments:dict[str,Any]|None=None):
        args=arguments or {}
        if command=='atlas.rescanDocument': return self._analyze(str(args['uri'])).to_dict()
        if command=='atlas.explainFinding': return {'code':args.get('code'),'documentation':'Atlas security diagnostic'}
        if command=='atlas.suppressFinding': return {'applied':False,'reason':'Suppression requires policy-file editing','request':args}
        raise KeyError(command)
    def handle(self,method:str,params:dict[str,Any]|None=None):
        p=params or {}
        table={'initialize':lambda:self.initialize(p.get('rootUri')),'shutdown':self.shutdown,'textDocument/didOpen':lambda:self.did_open(p['textDocument']['uri'],p['textDocument']['text'],p['textDocument'].get('version',1),p['textDocument'].get('languageId','java')).to_dict(),'textDocument/didChange':lambda:self.did_change(p['textDocument']['uri'],p['contentChanges'][-1]['text'],p['textDocument']['version']).to_dict(),'textDocument/didSave':lambda:self.did_save(p['textDocument']['uri'],p.get('text')).to_dict(),'textDocument/didClose':lambda:self.did_close(p['textDocument']['uri']).to_dict(),'textDocument/documentSymbol':lambda:[s.to_dict() for s in self.document_symbols(p['textDocument']['uri'])],'workspace/symbol':lambda:list(self.workspace_symbols(p.get('query',''))),'textDocument/codeAction':lambda:[a.to_dict() for a in self.code_actions(p['textDocument']['uri'])],'workspace/executeCommand':lambda:self.execute_command(p['command'],(p.get('arguments') or [{}])[0] if isinstance(p.get('arguments'),list) else p.get('arguments'))}
        if method not in table: raise KeyError(method)
        return table[method]()
