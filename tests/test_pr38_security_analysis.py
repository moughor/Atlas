import json
import pytest
from moughorai.security_analysis import *

L=SourceLocation('src/App.java',10)
def source(name='request.getParameter'): return Expression.call(name,location=L)
def var(name='input'): return Expression.variable(name,location=L)
def prog(assign=(),calls=(),config=()): return SecurityProgram(tuple(assign),tuple(calls),configuration=tuple(config))
def call(name,*args,line=20): return Invocation(name,tuple(args),SourceLocation('src/App.java',line))

def findings(p): return SecurityAnalyzer().analyze(p).findings

@pytest.mark.parametrize('sink,rule',[
 ('Statement.executeQuery','ATLAS-SQL-001'),('Statement.executeUpdate','ATLAS-SQL-001'),('Connection.prepareStatement','ATLAS-SQL-001'),('EntityManager.createNativeQuery','ATLAS-SQL-001'),
 ('Runtime.exec','ATLAS-CMD-001'),('ProcessBuilder','ATLAS-CMD-001'),('startProcess','ATLAS-CMD-001'),
 ('Files.readAllBytes','ATLAS-PATH-001'),('Files.write','ATLAS-PATH-001'),('FileInputStream','ATLAS-PATH-001'),('FileOutputStream','ATLAS-PATH-001'),('Paths.get','ATLAS-PATH-001'),
 ('URL.openConnection','ATLAS-SSRF-001'),('HttpClient.send','ATLAS-SSRF-001'),('RestTemplate.getForObject','ATLAS-SSRF-001'),('WebClient.get','ATLAS-SSRF-001'),
 ('ObjectInputStream.readObject','ATLAS-DESER-001'),('XMLDecoder.readObject','ATLAS-DESER-001'),('Class.forName','ATLAS-REFLECT-001'),('Method.invoke','ATLAS-REFLECT-001')])
def test_tainted_sinks(sink,rule):
 p=prog([Assignment('input',source(),L)],[call(sink,var())])
 assert findings(p)[0].rule_id==rule

@pytest.mark.parametrize('src',['request.getParameter','request.getHeader','request.getQueryString','Scanner.nextLine','System.getenv','System.getProperty','readLine','getInputStream'])
def test_sources(src):
 p=prog([Assignment('x',source(src),L)],[call('Runtime.exec',var('x'))])
 assert findings(p)

@pytest.mark.parametrize('san',['sanitize','escapeSql','normalizePath','validateUrl','allowlist','encodeForSQL'])
def test_sanitizers(san):
 p=prog([Assignment('x',source(),L),Assignment('safe',Expression.call(san,var('x'),location=L),L)],[call('Runtime.exec',var('safe'))])
 assert not findings(p)

def test_concat_propagates_taint():
 p=prog([Assignment('x',source(),L),Assignment('q',Expression.concat(Expression.literal('select '),var('x')),L)],[call('Statement.executeQuery',var('q'))])
 assert findings(p)[0].trace

def test_literal_is_safe(): assert not findings(prog(calls=[call('Runtime.exec',Expression.literal('date'))]))
def test_unknown_variable_is_safe(): assert not findings(prog(calls=[call('Runtime.exec',var('missing'))]))
def test_deduplicates_fingerprint():
 p=prog([Assignment('x',source(),L)],[call('Runtime.exec',var('x')),call('Runtime.exec',var('x'))])
 assert len(findings(p))==1

@pytest.mark.parametrize('secret',['AKIAABCDEFGHIJKLMNOP','password="supersecret123"','-----BEGIN PRIVATE KEY-----'])
def test_hardcoded_secrets(secret):
 fs=findings(prog([Assignment('x',Expression.literal(secret,L),L)]))
 assert fs[0].rule_id=='ATLAS-SECRET-001'

@pytest.mark.parametrize('alg',['MD5','SHA-1','SHA1','DES','DESede','RC4','AES/ECB/PKCS5Padding'])
def test_weak_crypto(alg):
 assert findings(prog(calls=[call('MessageDigest.getInstance',Expression.literal(alg))]))[0].rule_id=='ATLAS-CRYPTO-001'

def test_strong_crypto_safe(): assert not findings(prog(calls=[call('MessageDigest.getInstance',Expression.literal('SHA-256'))]))
def test_xxe(): assert findings(prog(calls=[call('DocumentBuilder.parse',var())]))[0].rule_id=='ATLAS-XXE-001'

@pytest.mark.parametrize('key,value,rule',[
 ('spring.security.csrf.enabled','false','ATLAS-SPRING-001'),('server.ssl.enabled','false','ATLAS-CONFIG-001'),('management.endpoints.web.exposure.include','*','ATLAS-SPRING-002')])
def test_config_rules(key,value,rule): assert findings(prog(config=[(key,value)]))[0].rule_id==rule

def test_safe_config(): assert not findings(prog(config=[('spring.security.csrf.enabled','true')]))
def test_statistics():
 r=SecurityAnalyzer().analyze(prog([Assignment('x',source(),L)],[call('Runtime.exec',var('x'))]))
 assert r.statistics.finding_count==1 and r.statistics.critical==1 and r.statistics.rule_count==11

def test_deterministic_order():
 p=prog([Assignment('x',source(),L)],[call('Runtime.exec',var('x'),line=30),call('Statement.executeQuery',var('x'),line=20)])
 assert [f.location.line for f in findings(p)]==[20,30]

def test_json_export():
 r=SecurityAnalyzer().analyze(prog([Assignment('x',source(),L)],[call('Runtime.exec',var('x'))]))
 d=json.loads(SecurityReportExporter().to_json(r)); assert d['findings'][0]['cwe']=='CWE-78'

def test_sarif_export():
 r=SecurityAnalyzer().analyze(prog([Assignment('x',source(),L)],[call('Runtime.exec',var('x'))]))
 d=json.loads(SecurityReportExporter().to_sarif(r)); assert d['version']=='2.1.0' and d['runs'][0]['results'][0]['ruleId']=='ATLAS-CMD-001'

def test_location_validation():
 with pytest.raises(ValueError): SourceLocation('',1)
 with pytest.raises(ValueError): SourceLocation('x',0)

def test_fingerprint():
 f=findings(prog([Assignment('x',source(),L)],[call('Runtime.exec',var('x'))]))[0]
 assert f.fingerprint=='ATLAS-CMD-001:src/App.java:20:1'
