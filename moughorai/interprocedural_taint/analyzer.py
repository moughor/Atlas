from __future__ import annotations

import re
from dataclasses import dataclass, field

from moughorai.java_security import JavaSourceUnit
from moughorai.security_analysis import Confidence, SecurityFinding, Severity, SourceLocation, TraceStep
from moughorai.security_analysis.rules import SANITIZERS, SOURCES, TAINT_RULES

from .models import (
    InterproceduralTaintMetrics, InterproceduralTaintReport, JavaMethod, JavaMethodId,
    JavaType, MethodSummary, TaintValue,
)
from .parser import JavaProgramParser

_ASSIGN = re.compile(r"^(?:(?:final\s+)?[\w.$<>?\[\],]+\s+)?(?P<target>(?:this\.)?[A-Za-z_$][\w$]*)\s*=\s*(?P<expr>.+)$", re.DOTALL)
_RETURN = re.compile(r"^return\s+(.+)$", re.DOTALL)
_CALL = re.compile(r"^(?P<prefix>(?:new\s+)?[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\((?P<args>.*)\)$", re.DOTALL)


@dataclass(slots=True)
class InterproceduralTaintAnalyzer:
    max_context_depth: int = 12
    max_summary_iterations: int = 20
    parser: JavaProgramParser = field(default_factory=JavaProgramParser)

    def analyze_units(self, units: tuple[JavaSourceUnit, ...] | list[JavaSourceUnit], entrypoints: tuple[str, ...] = ()) -> InterproceduralTaintReport:
        types = self.parser.parse_units(units)
        methods = {m.method_id: m for t in types for m in t.methods}
        simple_types = {t.simple_name: t.qualified_name for t in types}
        by_name: dict[tuple[str, int], list[JavaMethodId]] = {}
        for mid in methods:
            by_name.setdefault((mid.name, mid.arity), []).append(mid)
        for values in by_name.values(): values.sort(key=lambda item: item.qualified_name)

        summaries: dict[JavaMethodId, MethodSummary] = {mid: MethodSummary(mid) for mid in methods}
        iterations = 0
        unresolved: set[str] = set()
        for iterations in range(1, self.max_summary_iterations + 1):
            changed = False
            for mid in sorted(methods, key=lambda item: item.qualified_name):
                summary = self._summarize(methods[mid], summaries, methods, by_name, simple_types, unresolved)
                if summary != summaries[mid]: summaries[mid] = summary; changed = True
            if not changed: break

        roots = self._entry_methods(methods, entrypoints)
        findings: list[SecurityFinding] = []
        analyzed_contexts: set[tuple[JavaMethodId, tuple[bool, ...]]] = set()
        for root in roots:
            params = tuple(TaintValue.clean() for _ in root.parameters)
            self._execute(root, params, methods, by_name, simple_types, summaries, findings, analyzed_contexts, (), unresolved)

        unique = {f.fingerprint + ":" + "/".join(step.message for step in f.trace): f for f in findings}
        ordered = tuple(sorted(unique.values(), key=lambda f: (f.location.path, f.location.line, f.rule_id, tuple(s.message for s in f.trace))))
        calls = {call for summary in summaries.values() for call in summary.calls}
        metrics = InterproceduralTaintMetrics(len(types), len(methods), len(calls), len(analyzed_contexts), iterations, len(ordered), len(unresolved))
        warnings = tuple(f"Unresolved call: {name}" for name in sorted(unresolved))
        return InterproceduralTaintReport(ordered, tuple(summaries[mid] for mid in sorted(summaries, key=lambda item: item.qualified_name)), metrics, warnings)

    def _entry_methods(self, methods: dict[JavaMethodId, JavaMethod], names: tuple[str, ...]) -> tuple[JavaMethod, ...]:
        if names:
            wanted = set(names)
            selected = [m for m in methods.values() if m.method_id.qualified_name in wanted or m.method_id.name in wanted]
        else:
            selected = [m for m in methods.values() if self._is_entrypoint(m)]
            if not selected: selected = list(methods.values())
        return tuple(sorted(selected, key=lambda m: m.method_id.qualified_name))

    def _is_entrypoint(self, method: JavaMethod) -> bool:
        ann = {item.rsplit(".", 1)[-1] for item in method.annotations}
        return bool(ann & {"GetMapping", "PostMapping", "PutMapping", "DeleteMapping", "PatchMapping", "RequestMapping", "Path", "WebServlet"}) or method.method_id.name == "main"

    def _summarize(self, method, summaries, methods, by_name, simple_types, unresolved):
        symbolic = tuple(TaintValue.taint(f"parameter {name}", method.location) for name in method.parameters)
        sinks: list[tuple[str,int,SourceLocation]] = []
        fields: list[tuple[str,tuple[int,...]]] = []
        calls: list[JavaMethodId] = []
        returns = self._interpret(method, symbolic, methods, by_name, simple_types, summaries, [], set(), (), unresolved, sinks, fields, calls, summary_mode=True)
        tainted_params = tuple(i for i, name in enumerate(method.parameters) if any(any(f"parameter {name}" == step.message for step in value.trace) for value in returns))
        source_return = any(any(step.message.startswith("untrusted source:") for step in value.trace) for value in returns)
        sanitized = bool(returns) and all(not value.tainted for value in returns)
        return MethodSummary(method.method_id, tainted_params, source_return, sanitized, tuple(sorted(set(fields))), tuple(sinks), tuple(sorted(set(calls), key=lambda item:item.qualified_name)))

    def _execute(self, method, arguments, methods, by_name, simple_types, summaries, findings, contexts, stack, unresolved):
        key=(method.method_id, tuple(arg.tainted for arg in arguments))
        if key in contexts or len(stack) >= self.max_context_depth: return (TaintValue.clean(),)
        contexts.add(key)
        return self._interpret(method, arguments, methods, by_name, simple_types, summaries, findings, contexts, stack+(method.method_id,), unresolved, [], [], [], summary_mode=False)

    def _interpret(self, method, arguments, methods, by_name, simple_types, summaries, findings, contexts, stack, unresolved, sink_specs, field_specs, calls, summary_mode):
        env={name: arguments[i] if i < len(arguments) else TaintValue.clean() for i,name in enumerate(method.parameters)}
        fields: dict[str,TaintValue]={}
        returns=[]
        for line, statement in self._statements(method):
            loc=SourceLocation(method.location.path,line)
            clean=statement.strip().rstrip(";").strip()
            if not clean: continue
            if match:=_RETURN.match(clean):
                returns.append(self._eval(match.group(1),loc,method,env,fields,methods,by_name,simple_types,summaries,findings,contexts,stack,unresolved,calls,summary_mode)); continue
            if match:=_ASSIGN.match(clean):
                value=self._eval(match.group("expr"),loc,method,env,fields,methods,by_name,simple_types,summaries,findings,contexts,stack,unresolved,calls,summary_mode)
                target=match.group("target")
                if target.startswith("this."):
                    fields[target[5:]]=value
                    deps=tuple(i for i,p in enumerate(method.parameters) if any(step.message==f"parameter {p}" for step in value.trace))
                    field_specs.append((target[5:],deps))
                else: env[target]=value
                continue
            self._eval(clean,loc,method,env,fields,methods,by_name,simple_types,summaries,findings,contexts,stack,unresolved,calls,summary_mode,sink_specs)
        return tuple(returns) or (TaintValue.clean(),)

    def _eval(self,text,loc,method,env,fields,methods,by_name,simple_types,summaries,findings,contexts,stack,unresolved,calls,summary_mode,sink_specs=None):
        text=self._strip_outer(text.strip())
        parts=self._split_top(text,"+")
        if len(parts)>1:
            return TaintValue.merge(*(self._eval(p,loc,method,env,fields,methods,by_name,simple_types,summaries,findings,contexts,stack,unresolved,calls,summary_mode,sink_specs) for p in parts))
        if text.startswith('"') or text.startswith("'") or re.fullmatch(r"-?\d+(?:\.\d+)?|true|false|null",text): return TaintValue.clean()
        if text.startswith("this.") and re.fullmatch(r"this\.[A-Za-z_$][\w$]*",text): return fields.get(text[5:],TaintValue.clean())
        if text in env: return env[text]
        call=self._parse_call(text)
        if not call: return TaintValue.clean()
        name,args=call
        values=tuple(self._eval(a,loc,method,env,fields,methods,by_name,simple_types,summaries,findings,contexts,stack,unresolved,calls,summary_mode,sink_specs) for a in args)
        normalized=name.replace("new ","")
        if any(normalized.endswith(source) for source in SOURCES): return TaintValue.taint(f"untrusted source: {normalized}",loc)
        if any(normalized.endswith(sanitizer) for sanitizer in SANITIZERS): return TaintValue.clean()
        self._check_sink(normalized,values,loc,findings,sink_specs,summary_mode)
        target=self._resolve_call(normalized,len(args),method,methods,by_name,simple_types)
        if target:
            calls.append(target)
            if summary_mode:
                summary=summaries.get(target,MethodSummary(target))
                result=TaintValue.merge(*(values[i] for i in summary.tainted_return_parameters if i<len(values)))
                if summary.source_return: result=TaintValue.merge(result,TaintValue.taint(f"source returned by {target.qualified_name}",loc))
                return result.append(f"returned from {target.qualified_name}",loc) if result.tainted else result
            callee=methods[target]
            returned=self._execute(callee,values,methods,by_name,simple_types,summaries,findings,contexts,stack,unresolved)
            result=TaintValue.merge(*returned)
            return result.append(f"returned from {target.qualified_name}",loc) if result.tainted else result
        if "." not in normalized or normalized.split(".")[-1] not in {"println","log","debug","info","warn","error"}: unresolved.add(f"{normalized}/{len(args)}")
        return TaintValue.merge(*values)

    def _check_sink(self,name,values,loc,findings,sink_specs,summary_mode):
        for rule in TAINT_RULES:
            if not any(name.endswith(sink) for sink in rule.sinks): continue
            for index in rule.argument_indexes:
                if index>=len(values): continue
                if summary_mode:
                    if values[index].tainted: sink_specs.append((rule.rule_id,index,loc))
                elif values[index].tainted:
                    findings.append(SecurityFinding(rule.rule_id,rule.title,rule.message,rule.severity,Confidence.HIGH,rule.cwe,rule.owasp,loc,values[index].trace+(TraceStep(f"tainted value reaches {name}",loc),),properties=(("analysis","interprocedural"),)))

    def _resolve_call(self,name,arity,current,methods,by_name,simple_types):
        member=name.split(".")[-1]
        qualifier=name.rsplit(".",1)[0] if "." in name else ""
        candidates=by_name.get((member,arity),[])
        if not candidates: return None
        if not qualifier:
            same=[mid for mid in candidates if mid.owner==current.method_id.owner]
            return same[0] if same else (candidates[0] if len(candidates)==1 else None)
        q=qualifier.split(".")[-1]
        owner=simple_types.get(q,q)
        exact=[mid for mid in candidates if mid.owner==owner or mid.owner.endswith("."+owner)]
        return exact[0] if exact else (candidates[0] if len(candidates)==1 else None)

    def _statements(self,method):
        out=[]; buf=[]; depth=0; quote=""; escape=False; start=method.location.line
        for offset,line in enumerate(method.body.splitlines(),1):
            if not buf and line.strip(): start=method.location.line+offset
            for ch in line+"\n":
                buf.append(ch)
                if quote:
                    if escape: escape=False
                    elif ch=="\\": escape=True
                    elif ch==quote: quote=""
                    continue
                if ch in {'"',"'"}: quote=ch
                elif ch in "([{": depth+=1
                elif ch in ")]}": depth=max(0,depth-1)
                elif ch==";" and depth==0: out.append((start,"".join(buf))); buf=[]
        if "".join(buf).strip(): out.append((start,"".join(buf)))
        return tuple(out)

    def _parse_call(self,text):
        if not text.endswith(")"):
            return None
        depth = 0
        quote = ""
        opening = None
        for index in range(len(text) - 1, -1, -1):
            char = text[index]
            if quote:
                if char == quote and (index == 0 or text[index - 1] != "\\"):
                    quote = ""
                continue
            if char in {'"', "'"}:
                quote = char
            elif char == ")":
                depth += 1
            elif char == "(":
                depth -= 1
                if depth == 0:
                    opening = index
                    break
        if opening is None:
            return None
        prefix = text[:opening].strip()
        if not prefix:
            return None
        prefix = re.sub(r"\([^()]*\)", "", prefix)
        args=self._split_top(text[opening + 1:-1],",")
        if len(args)==1 and not args[0]:args=()
        return prefix,args

    def _split_top(self,text,delimiter):
        out=[];start=0;depth=0;quote="";escape=False
        for i,ch in enumerate(text):
            if quote:
                if escape:escape=False
                elif ch=="\\":escape=True
                elif ch==quote:quote=""
                continue
            if ch in {'"',"'"}:quote=ch
            elif ch in "([{":depth+=1
            elif ch in ")]}":depth-=1
            elif ch==delimiter and depth==0:out.append(text[start:i].strip());start=i+1
        out.append(text[start:].strip());return tuple(out)

    def _strip_outer(self,text):
        while text.startswith("(") and text.endswith(")"):
            depth=0;valid=True
            for i,ch in enumerate(text):
                if ch=="(":depth+=1
                elif ch==")":depth-=1
                if depth==0 and i<len(text)-1:valid=False;break
            if not valid:break
            text=text[1:-1].strip()
        return text
