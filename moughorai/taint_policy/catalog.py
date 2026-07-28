from __future__ import annotations
from .models import MatchMode, SymbolMatcher, TaintPolicy
from moughorai.security_analysis.models import Severity

def default_policies():
    M=SymbolMatcher
    return (
        TaintPolicy('ATLAS-POLICY-SQL-001','SQL injection flow','Untrusted input reaches a database query sink.',(M('request',MatchMode.CONTAINS),M('param',MatchMode.SUFFIX)),(M('query',MatchMode.CONTAINS),M('execute',MatchMode.CONTAINS)),(M('sanitizeSql',MatchMode.EXACT),M('prepared',MatchMode.CONTAINS)),Severity.CRITICAL,cwe='CWE-89'),
        TaintPolicy('ATLAS-POLICY-CMD-001','Command injection flow','Untrusted input reaches a command execution sink.',(M('request',MatchMode.CONTAINS),M('input',MatchMode.CONTAINS)),(M('exec',MatchMode.CONTAINS),M('command',MatchMode.CONTAINS)),(M('allowlist',MatchMode.CONTAINS),),Severity.CRITICAL,cwe='CWE-78'),
        TaintPolicy('ATLAS-POLICY-PATH-001','Path traversal flow','Untrusted input reaches a filesystem path sink.',(M('request',MatchMode.CONTAINS),M('pathParam',MatchMode.EXACT)),(M('file',MatchMode.CONTAINS),M('path',MatchMode.SUFFIX)),(M('normalize',MatchMode.CONTAINS),),Severity.HIGH,cwe='CWE-22'),
    )
