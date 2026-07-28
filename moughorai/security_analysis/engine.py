from __future__ import annotations
import re
from dataclasses import dataclass
from .models import *
from .rules import TAINT_RULES, SOURCES, SANITIZERS

@dataclass(frozen=True, slots=True)
class _Taint:
    tainted: bool=False
    trace: tuple[TraceStep,...]=()

class SecurityAnalyzer:
    SECRET_PATTERNS=(
      ('AWS access key', re.compile(r'AKIA[0-9A-Z]{16}')),
      ('Private key', re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')),
      ('Generic secret', re.compile(r'(?i)(?:password|passwd|secret|api[_-]?key|token)\s*[:=]\s*["\']([^"\']{8,})["\']')),
    )
    WEAK_CRYPTO={'MD5':'CWE-327','SHA-1':'CWE-327','SHA1':'CWE-327','DES':'CWE-327','DESede':'CWE-327','RC4':'CWE-327','AES/ECB':'CWE-327'}

    def analyze(self, program: SecurityProgram) -> SecurityReport:
        env: dict[str,_Taint]={}
        findings=[]
        for a in program.assignments:
            env[a.target]=self._eval(a.value, env)
            findings.extend(self._literal_findings(a.value, a.location))
            findings.extend(self._credential_assignment_findings(a))
        for call in program.invocations:
            for arg in call.arguments: findings.extend(self._literal_findings(arg, call.location))
            findings.extend(self._taint_findings(call, env))
            findings.extend(self._api_findings(call))
        findings.extend(self._config_findings(program))
        unique={f.fingerprint:f for f in findings}
        ordered=tuple(sorted(unique.values(), key=lambda f:(f.location.path,f.location.line,f.rule_id)))
        counts={s:sum(f.severity is s for f in ordered) for s in Severity}
        stats=ScanStatistics(len(TAINT_RULES)+5,len(ordered),counts[Severity.CRITICAL],counts[Severity.HIGH],counts[Severity.MEDIUM],counts[Severity.LOW],counts[Severity.INFO])
        return SecurityReport(ordered,stats)

    def _eval(self,e,env):
        if e.kind is ValueKind.VARIABLE: return env.get(str(e.value),_Taint())
        if e.kind is ValueKind.CALL:
            name=str(e.value)
            if any(name.endswith(s) for s in SANITIZERS): return _Taint(False,(TraceStep(f'sanitized by {name}',e.location),))
            if any(name.endswith(s) for s in SOURCES): return _Taint(True,(TraceStep(f'untrusted source: {name}',e.location),))
        parts=[self._eval(p,env) for p in e.parts]
        tainted=[p for p in parts if p.tainted]
        return _Taint(bool(tainted),tuple(step for p in tainted for step in p.trace))

    def _taint_findings(self,call,env):
        out=[]
        for rule in TAINT_RULES:
            if not any(call.name.endswith(s) for s in rule.sinks): continue
            for i in rule.argument_indexes:
                if i>=len(call.arguments): continue
                t=self._eval(call.arguments[i],env)
                if t.tainted:
                    trace=t.trace+(TraceStep(f'tainted argument reaches {call.name}',call.location),)
                    out.append(SecurityFinding(rule.rule_id,rule.title,rule.message,rule.severity,Confidence.HIGH,rule.cwe,rule.owasp,call.location,trace))
        return out

    def _literal_findings(self,e,loc):
        out=[]
        if e.kind is ValueKind.LITERAL and isinstance(e.value,str):
            for label,pat in self.SECRET_PATTERNS:
                if pat.search(e.value):
                    out.append(SecurityFinding('ATLAS-SECRET-001','Hardcoded secret',f'{label} appears to be hardcoded.',Severity.HIGH,Confidence.HIGH,'CWE-798','A07:2021',e.location or loc))
        for p in e.parts: out.extend(self._literal_findings(p,loc))
        return out

    def _credential_assignment_findings(self, assignment):
        value = assignment.value
        if value.kind is not ValueKind.LITERAL or not isinstance(value.value, str):
            return []
        target = assignment.target.lower().replace("_", "").replace("-", "")
        credential_names = ("password", "passwd", "secret", "apikey", "accesstoken", "authtoken", "privatekey")
        if not any(name in target for name in credential_names):
            return []
        candidate = value.value.strip()
        if len(candidate) < 8 or candidate.lower() in {"password", "changeme", "example", "dummy", "placeholder"}:
            return []
        return [SecurityFinding(
            'ATLAS-SECRET-001', 'Hardcoded secret',
            f'Credential-like variable {assignment.target} contains a hardcoded value.',
            Severity.HIGH, Confidence.HIGH, 'CWE-798', 'A07:2021',
            value.location or assignment.location,
            properties=(('variable', assignment.target),),
        )]

    def _api_findings(self,call):
        out=[]
        if call.name.endswith(('MessageDigest.getInstance','Cipher.getInstance')) and call.arguments:
            a=call.arguments[0]
            if a.kind is ValueKind.LITERAL and isinstance(a.value,str):
                upper=a.value.upper()
                if any(x.upper() in upper for x in self.WEAK_CRYPTO):
                    out.append(SecurityFinding('ATLAS-CRYPTO-001','Weak cryptography',f'Weak cryptographic algorithm: {a.value}.',Severity.HIGH,Confidence.HIGH,'CWE-327','A02:2021',call.location))
        if call.name.endswith('DocumentBuilderFactory.setFeature') and len(call.arguments)>=2:
            if call.arguments[1].kind is ValueKind.LITERAL and call.arguments[1].value is False:
                return out
        if call.name.endswith(('DocumentBuilder.parse','SAXParser.parse')):
            out.append(SecurityFinding('ATLAS-XXE-001','XML external entity injection','XML parsing may allow external entities.',Severity.HIGH,Confidence.MEDIUM,'CWE-611','A05:2021',call.location))
        return out

    def _config_findings(self,program):
        cfg=dict(program.configuration); out=[]
        def add(rule,title,msg,sev,cwe,owasp,key):
            out.append(SecurityFinding(rule,title,msg,sev,Confidence.HIGH,cwe,owasp,SourceLocation(cfg.get('config_path','application.properties'),1),properties=(('configuration',key),)))
        if cfg.get('spring.security.csrf.enabled','true').lower()=='false': add('ATLAS-SPRING-001','CSRF protection disabled','Spring Security CSRF protection is disabled.',Severity.HIGH,'CWE-352','A01:2021','spring.security.csrf.enabled')
        if cfg.get('server.ssl.enabled','true').lower()=='false': add('ATLAS-CONFIG-001','TLS disabled','The application server has TLS disabled.',Severity.MEDIUM,'CWE-319','A02:2021','server.ssl.enabled')
        if cfg.get('management.endpoints.web.exposure.include')=='*': add('ATLAS-SPRING-002','All actuator endpoints exposed','All Spring Boot actuator endpoints are exposed.',Severity.HIGH,'CWE-284','A05:2021','management.endpoints.web.exposure.include')
        return out
