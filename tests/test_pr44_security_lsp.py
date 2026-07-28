import pytest
from moughorai.security_lsp import *

VULN='''class Demo { void run(HttpServletRequest request, Statement stmt) throws Exception { String id = request.getParameter("id"); stmt.executeQuery("select * from t where id=" + id); } }'''
SAFE='class Demo { void run() { String value = "safe"; } }'

def test_position_validation():
    with pytest.raises(ValueError): Position(-1,0)

def test_range_validation():
    with pytest.raises(ValueError): Range(Position(1,0),Position(0,0))

def test_position_dict(): assert Position(1,2).to_dict()=={'line':1,'character':2}
def test_range_dict(): assert Range(Position(0,1),Position(0,2)).to_dict()['end']['character']==2
def test_store_open_get():
    s=DocumentStore(); d=s.open('file:///A.java','x',1); assert s.get(d.uri)==d

def test_store_change():
    s=DocumentStore(); s.open('u','a',1); assert s.change('u','b',2).text=='b'
def test_store_rejects_old_version():
    s=DocumentStore(); s.open('u','a',2)
    with pytest.raises(ValueError): s.change('u','b',2)
def test_store_close():
    s=DocumentStore(); s.open('u','a'); assert s.close('u') is not None and len(s)==0
def test_store_require_missing():
    with pytest.raises(KeyError): DocumentStore().require('u')
def test_store_sorted_uris():
    s=DocumentStore(); s.open('b',''); s.open('a',''); assert s.uris()==('a','b')
def test_document_offsets():
    d=TextDocument('u','ab\ncd',1); assert d.offset_at(1,1)==4 and d.position_at(4)==(1,1)
def test_document_offset_clamps(): assert TextDocument('u','a',1).offset_at(9,9)==1
def test_path_to_uri(tmp_path): assert path_to_uri(tmp_path).startswith('file:')
def test_initialize():
    r=SecurityLanguageServer().initialize('file:///root'); assert r['capabilities']['codeActionProvider']
def test_shutdown():
    s=SecurityLanguageServer(); assert s.shutdown() is None and s.shutdown_requested
def test_open_safe_empty(): assert SecurityLanguageServer().did_open('file:///Demo.java',SAFE).diagnostics==()
def test_open_vulnerable_has_diagnostic(): assert SecurityLanguageServer().did_open('file:///Demo.java',VULN).diagnostics
def test_diagnostic_zero_based():
    d=SecurityLanguageServer().did_open('file:///Demo.java',VULN).diagnostics[0]; assert d.range.start.line>=0 and d.range.start.character>=0
def test_diagnostic_metadata():
    d=SecurityLanguageServer().did_open('file:///Demo.java',VULN).diagnostics[0]; assert {'fingerprint','cwe','owasp'} <= dict(d.data).keys()
def test_diagnostic_to_dict():
    d=SecurityLanguageServer().did_open('file:///Demo.java',VULN).diagnostics[0].to_dict(); assert d['source']=='atlas' and isinstance(d['severity'],int)
def test_change_reanalyzes():
    s=SecurityLanguageServer(); s.did_open('file:///Demo.java',VULN,1); assert s.did_change('file:///Demo.java',SAFE,2).diagnostics==()
def test_save_reanalyzes():
    s=SecurityLanguageServer(); s.did_open('file:///Demo.java',SAFE,1); assert s.did_save('file:///Demo.java',VULN).diagnostics
def test_close_clears():
    s=SecurityLanguageServer(); s.did_open('file:///Demo.java',VULN); assert s.did_close('file:///Demo.java').diagnostics==()
def test_non_java_skipped(): assert SecurityLanguageServer().did_open('file:///x.txt',VULN,language_id='text').diagnostics==()
def test_document_symbols_type(): assert any(x.name=='Demo' for x in document_symbols(SAFE))
def test_document_symbols_method(): assert any(x.name=='run' for x in document_symbols(SAFE))
def test_symbols_ordered():
    names=[x.name for x in document_symbols('class Z { void b(){} void a(){} }')]; assert names[0]=='Z'
def test_server_document_symbols():
    s=SecurityLanguageServer(); s.did_open('file:///Demo.java',SAFE); assert s.document_symbols('file:///Demo.java')
def test_workspace_symbols():
    s=SecurityLanguageServer(); s.did_open('file:///A.java','class Alpha {}'); s.did_open('file:///B.java','class Beta {}'); assert len(s.workspace_symbols())==2
def test_workspace_symbol_query():
    s=SecurityLanguageServer(); s.did_open('file:///A.java','class Alpha {}'); s.did_open('file:///B.java','class Beta {}'); assert [x['name'] for x in s.workspace_symbols('bet')]==['Beta']
def test_code_actions_empty():
    s=SecurityLanguageServer(); s.did_open('file:///D.java',SAFE); assert s.code_actions('file:///D.java')==()
def test_code_actions_for_finding():
    s=SecurityLanguageServer(); s.did_open('file:///D.java',VULN); titles=[a.title for a in s.code_actions('file:///D.java')]; assert any('Suppress' in x for x in titles) and 'Rescan document' in titles
def test_code_action_dict_command():
    s=SecurityLanguageServer(); s.did_open('file:///D.java',VULN); assert any('command' in a.to_dict() for a in s.code_actions('file:///D.java'))
def test_execute_rescan():
    s=SecurityLanguageServer(); s.did_open('file:///D.java',VULN); assert s.execute_command('atlas.rescanDocument',{'uri':'file:///D.java'})['diagnostics']
def test_execute_explain(): assert SecurityLanguageServer().execute_command('atlas.explainFinding',{'code':'X'})['code']=='X'
def test_execute_suppress_is_safe(): assert SecurityLanguageServer().execute_command('atlas.suppressFinding',{})['applied'] is False
def test_execute_unknown():
    with pytest.raises(KeyError): SecurityLanguageServer().execute_command('x')
def test_handle_initialize(): assert SecurityLanguageServer().handle('initialize',{})['serverInfo']['version']=='0.44'
def test_handle_open():
    s=SecurityLanguageServer(); r=s.handle('textDocument/didOpen',{'textDocument':{'uri':'file:///D.java','text':VULN,'version':1,'languageId':'java'}}); assert r['diagnostics']
def test_handle_change():
    s=SecurityLanguageServer(); s.did_open('file:///D.java',VULN); r=s.handle('textDocument/didChange',{'textDocument':{'uri':'file:///D.java','version':2},'contentChanges':[{'text':SAFE}]}); assert r['diagnostics']==[]
def test_handle_symbols():
    s=SecurityLanguageServer(); s.did_open('file:///D.java',SAFE); assert s.handle('textDocument/documentSymbol',{'textDocument':{'uri':'file:///D.java'}})
def test_handle_workspace_symbols():
    s=SecurityLanguageServer(); s.did_open('file:///D.java',SAFE); assert s.handle('workspace/symbol',{'query':'Demo'})
def test_handle_code_action():
    s=SecurityLanguageServer(); s.did_open('file:///D.java',VULN); assert s.handle('textDocument/codeAction',{'textDocument':{'uri':'file:///D.java'}})
def test_handle_unknown():
    with pytest.raises(KeyError): SecurityLanguageServer().handle('unknown')
def test_publish_omits_none_version(): assert 'version' not in PublishDiagnostics('u',None,()).to_dict()
def test_publish_includes_version(): assert PublishDiagnostics('u',2,()).to_dict()['version']==2
def test_server_capabilities_dict(): assert ServerCapabilities().to_dict()['textDocumentSync']==1
def test_text_edit_dict(): assert TextEdit(Range(Position(0,0),Position(0,0)),'x').to_dict()['newText']=='x'
def test_diagnostics_deterministic():
    s=SecurityLanguageServer(); a=s.did_open('file:///D.java',VULN).to_dict(); b=s.did_save('file:///D.java').to_dict(); assert a==b
def test_multiple_documents_independent():
    s=SecurityLanguageServer(); s.did_open('file:///A.java',VULN); s.did_open('file:///B.java',SAFE); assert s.diagnostics('file:///A.java') and not s.diagnostics('file:///B.java')
