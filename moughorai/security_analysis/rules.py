from __future__ import annotations
from dataclasses import dataclass
from .models import Severity

@dataclass(frozen=True, slots=True)
class TaintRule:
    rule_id: str; title: str; cwe: str; owasp: str; severity: Severity
    sinks: tuple[str, ...]; argument_indexes: tuple[int, ...] = (0,)
    message: str = 'Untrusted data reaches a security-sensitive operation.'

TAINT_RULES = (
 TaintRule('ATLAS-SQL-001','SQL injection','CWE-89','A03:2021',Severity.CRITICAL,('executeQuery','executeUpdate','prepareStatement','createNativeQuery')),
 TaintRule('ATLAS-CMD-001','Command injection','CWE-78','A03:2021',Severity.CRITICAL,('Runtime.exec','ProcessBuilder','startProcess')),
 TaintRule('ATLAS-PATH-001','Path traversal','CWE-22','A01:2021',Severity.HIGH,('Files.readAllBytes','Files.write','FileInputStream','FileOutputStream','Paths.get')),
 TaintRule('ATLAS-SSRF-001','Server-side request forgery','CWE-918','A10:2021',Severity.HIGH,('URL.openConnection','HttpClient.send','RestTemplate.getForObject','WebClient.get')),
 TaintRule('ATLAS-DESER-001','Insecure deserialization','CWE-502','A08:2021',Severity.CRITICAL,('ObjectInputStream.readObject','XMLDecoder.readObject')),
 TaintRule('ATLAS-REFLECT-001','Unsafe reflection','CWE-470','A03:2021',Severity.HIGH,('Class.forName','Method.invoke')),
)
SOURCES=('request.getParameter','request.getHeader','request.getQueryString','Scanner.nextLine','System.getenv','System.getProperty','readLine','getInputStream')
SANITIZERS=('sanitize','escapeSql','normalizePath','validateUrl','allowlist','encodeForSQL')
