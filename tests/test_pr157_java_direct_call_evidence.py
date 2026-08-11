from __future__ import annotations

import json
from pathlib import Path

from moughorai.ai_context.analyzer_registry import JavaLanguageAnalyzer
from moughorai.java_code_intelligence.call_sites import (
    CallResolutionState,
    InvocationKind,
)
from moughorai.java_code_intelligence.code_graph import CodeGraphEdgeKind
from moughorai.workspace import Project


def _analyze(tmp_path: Path, source_text: str):
    project = tmp_path / 'project'
    source = project / 'src/main/java/demo/Calls.java'
    source.parent.mkdir(parents=True)
    source.write_text(source_text, encoding='utf-8')
    document = JavaLanguageAnalyzer().analyze(
        Project('demo', project), (source,), {},
    )
    return (
        document.require_artifact('java_code_graph'),
        document.require_artifact('java_callable_index'),
    )


def _site(
    graph,
    member: str,
    receiver: str | None = None,
    kind: InvocationKind | None = None,
):
    matches = tuple(
        item for item in graph.call_sites
        if item.request.member_name == member
        and (receiver is None or item.request.receiver == receiver)
        and (kind is None or item.request.invocation_kind is kind)
    )
    assert len(matches) == 1, (member, receiver, matches)
    return matches[0]


def test_exact_direct_calls_and_pr156_identity_mapping(tmp_path: Path) -> None:
    graph, callable_index = _analyze(tmp_path, '''package demo;
class Parent { void parent() {} }
class Helper {
  Helper(int value) {}
  static void stat() {}
  void instance() {}
  void pick(String value) {}
  void pick(int value) {}
}
class App extends Parent {
  void local() {}
  void calls(Helper helper) {
    Helper.stat();
    helper.instance();
    new Helper(1);
    this.local();
    super.parent();
    helper.pick("value");
    Helper::stat;
    external.Client.send();
    Class.forName("demo.Helper");
  }
}
''')
    entries = {
        item.canonical_subject_id: item for item in callable_index.entries
    }

    for member, receiver in (
        ('stat', 'Helper'),
        ('instance', 'helper'),
        ('local', 'this'),
        ('parent', 'super'),
        ('pick', 'helper'),
    ):
        evidence = _site(
            graph, member, receiver, InvocationKind.METHOD_INVOCATION,
        )
        assert evidence.state is CallResolutionState.RESOLVED
        assert evidence.target_subject_id in entries
        assert evidence.request.caller_subject_id in entries
        assert evidence.request.caller_normalized_key == (
            entries[evidence.request.caller_subject_id].identity.normalized_key
        )

    constructor = _site(graph, '<init>')
    assert constructor.state is CallResolutionState.RESOLVED
    assert constructor.target_subject_id in entries
    assert entries[constructor.target_subject_id].identity.name == '<init>'

    method_reference = _site(
        graph, 'stat', 'Helper', InvocationKind.METHOD_INVOCATION,
    )
    references = tuple(
        item for item in graph.call_sites
        if item.request.invocation_kind is InvocationKind.METHOD_REFERENCE
    )
    assert len(references) == 1
    assert references[0].state is CallResolutionState.RESOLVED
    assert any(
        edge.kind is CodeGraphEdgeKind.METHOD_REFERENCE
        and edge.evidence_id == references[0].evidence_id
        for edge in graph.edges
    )
    assert method_reference.request.source_path == (
        'src/main/java/demo/Calls.java'
    )

    static_call = tuple(
        item for item in graph.call_sites
        if item.request.member_name == 'stat'
        and item.request.invocation_kind is InvocationKind.METHOD_INVOCATION
    )[0]
    assert static_call.request.source_range.start.line == 13
    assert static_call.request.source_range.start.column == 5
    assert static_call.request.source_range.end.column == 18

    external = _site(graph, 'send', 'external.Client')
    reflection = _site(graph, 'forName', 'Class')
    assert external.state is CallResolutionState.EXTERNAL
    assert reflection.state is CallResolutionState.UNSUPPORTED
    assert graph.coverage.total_call_sites == 9
    assert graph.coverage.callable_bodies_examined == 8
    assert graph.coverage.callable_bodies_unavailable == 0
    assert graph.coverage.resolved_call_sites == 7
    assert graph.coverage.external_call_sites == 1
    assert graph.coverage.unsupported_call_sites == 1
    assert graph.coverage.constructor_calls == 1
    assert graph.coverage.method_references == 1


def test_overloads_and_static_imports_are_conservative(tmp_path: Path) -> None:
    explicit, _ = _analyze(tmp_path / 'explicit', '''package demo;
import static demo.Util.ping;
class Util { static void ping() {} }
class App { void run() { ping(); } }
''')
    call = _site(explicit, 'ping')
    assert call.state is CallResolutionState.RESOLVED

    wildcard, _ = _analyze(tmp_path / 'wildcard', '''package demo;
import static demo.Util.*;
class Util { static void ping() {} }
class App { void run() { ping(); } }
''')
    call = _site(wildcard, 'ping')
    assert call.state is CallResolutionState.AMBIGUOUS
    assert len(call.candidate_target_ids) == 1

    overloads, _ = _analyze(tmp_path / 'overloads', '''package demo;
class App {
  void pick(String value) {}
  void pick(Integer value) {}
  void exact() { pick("value"); }
  void ambiguous() { pick(null); }
}
''')
    exact = tuple(
        item for item in overloads.call_sites
        if item.request.member_name == 'pick'
        and item.request.source_range.start.line == 5
    )[0]
    ambiguous = tuple(
        item for item in overloads.call_sites
        if item.request.member_name == 'pick'
        and item.request.source_range.start.line == 6
    )[0]
    assert exact.state is CallResolutionState.RESOLVED
    assert ambiguous.state is CallResolutionState.AMBIGUOUS
    assert len(ambiguous.candidate_target_ids) == 2


def test_interface_and_virtual_dispatch_retain_candidate_sets(
    tmp_path: Path,
) -> None:
    graph, _ = _analyze(tmp_path, '''package demo;
interface Contract { void execute(); }
class ContractImpl implements Contract { public void execute() {} }
class Base { void work() {} }
class Child extends Base { @Override void work() {} }
class App {
  void run(Contract contract, Base base) {
    contract.execute();
    base.work();
  }
}
''')
    interface_call = _site(graph, 'execute', 'contract')
    virtual_call = _site(graph, 'work', 'base')
    for evidence in (interface_call, virtual_call):
        assert evidence.state is CallResolutionState.POLYMORPHIC
        assert evidence.declared_target_id is not None
        assert len(evidence.candidate_target_ids) == 1
        target_ids = {
            edge.target_subject_id for edge in graph.edges
            if edge.evidence_id == evidence.evidence_id
        }
        assert target_ids == {
            evidence.declared_target_id,
            *evidence.candidate_target_ids,
        }
    assert graph.coverage.callable_bodies_examined == 4
    assert graph.coverage.callable_bodies_unavailable == 1
    assert graph.coverage.polymorphic_call_sites == 2


def test_local_receiver_and_constructor_reference_are_represented(
    tmp_path: Path,
) -> None:
    graph, _ = _analyze(tmp_path, '''package demo;
class Helper { Helper() {} void instance() {} }
class App {
  Helper field;
  void run() {
    final Helper local = new Helper();
    local.instance();
    var inferred = new Helper();
    inferred.instance();
    this.field.instance();
    Helper::new;
  }
}
''')

    local = _site(graph, 'instance', 'local')
    inferred = _site(graph, 'instance', 'inferred')
    field = _site(graph, 'instance', 'this.field')
    constructor_reference = _site(
        graph, 'new', 'Helper', InvocationKind.METHOD_REFERENCE,
    )
    assert local.state is CallResolutionState.RESOLVED
    assert local.request.owner_type_hints == ('demo.Helper',)
    assert inferred.state is CallResolutionState.UNSUPPORTED
    assert inferred.request.owner_type_hints == ()
    assert field.state is CallResolutionState.RESOLVED
    assert field.request.owner_type_hints == ('demo.Helper',)
    assert constructor_reference.state is CallResolutionState.RESOLVED
    assert any(
        edge.kind is CodeGraphEdgeKind.METHOD_REFERENCE
        and edge.evidence_id == constructor_reference.evidence_id
        for edge in graph.edges
    )


def test_unsupported_receiver_and_source_safety(tmp_path: Path) -> None:
    graph, _ = _analyze(tmp_path, '''package demo;
class Helper { void run() {} }
class App {
  Helper factory() { return new Helper(); }
  <T> void generic() {}
  void invoke() { factory().run(); this.<String>generic(); }
}
''')
    run = _site(graph, 'run')
    generic = _site(graph, 'generic')
    assert run.state is CallResolutionState.UNSUPPORTED
    assert generic.state is CallResolutionState.UNSUPPORTED
    payload = json.dumps(graph.to_dict(), sort_keys=True)
    assert str(tmp_path.resolve()) not in payload
    assert 'factory().run' not in payload
    assert 'source_text' not in payload
    assert 'snippet' not in payload
    assert 'source_body' not in payload
    assert all(
        edge.caller_subject_id == run.request.caller_subject_id
        for edge in graph.edges
        if edge.evidence_id == run.evidence_id
    )


def test_polymorphic_candidate_expansion_is_bounded(tmp_path: Path) -> None:
    implementations = '\n'.join(
        f'class Impl{number:02d} implements Contract '
        '{ public void execute() {} }'
        for number in range(70)
    )
    graph, _ = _analyze(tmp_path, (
        'package demo;\n'
        'interface Contract { void execute(); }\n'
        f'{implementations}\n'
        'class App { void run(Contract value) { value.execute(); } }\n'
    ))

    evidence = _site(graph, 'execute', 'value')
    assert evidence.state is CallResolutionState.POLYMORPHIC
    assert len(evidence.candidate_target_ids) == 64
    assert any('6 represented dispatch target(s)' in item for item in evidence.limitations)


def test_parse_failure_is_explicit_in_code_graph_coverage(
    tmp_path: Path,
) -> None:
    graph, _ = _analyze(
        tmp_path,
        'package demo; class Broken { void run() { missing(',
    )

    assert graph.coverage.extraction_failures == 1
    assert graph.coverage.callable_bodies_examined == 0
    assert graph.coverage.total_call_sites == 0
    assert any(
        item.code == 'call_site_parse_failure'
        for item in graph.diagnostics
    )


def test_unicode_java_receivers_use_existing_pr156_identities(
    tmp_path: Path,
) -> None:
    graph, callable_index = _analyze(tmp_path, '''package δοκιμή;
class Βοήθεια { static void στόχος() {} void appeler() {} }
class App {
  Βοήθεια élève;
  void caller() { Βοήθεια.στόχος(); élève.appeler(); }
}
''')
    entries = {
        item.canonical_subject_id: item for item in callable_index.entries
    }
    greek = _site(graph, 'στόχος', 'Βοήθεια')
    accented = _site(graph, 'appeler', 'élève')

    assert greek.state is CallResolutionState.RESOLVED
    assert accented.state is CallResolutionState.RESOLVED
    assert greek.target_subject_id in entries
    assert accented.target_subject_id in entries
    assert graph.coverage.resolved_call_sites == 2


def test_ascii_evidence_id_and_pr156_digest_remain_byte_compatible(
    tmp_path: Path,
) -> None:
    graph, callable_index = _analyze(tmp_path, '''package demo;
class Helper { static void target() {} }
class App { void caller() { Helper.target(); } }
''')

    assert tuple(item.evidence_id for item in graph.call_sites) == (
        'evidence:55173c35e60b712445833f6a6e4f075126a3660912fba678f32fe6a1266150a8',
    )
    assert graph.digest == (
        'ba55cb7ff0f89098568390a2e58ab07449ddbc5cc6b6fc2358151338d6839c60'
    )
    assert callable_index.digest == (
        '8570535d980660241629796e732685d07fe0ce345e1613debbe785091372ed20'
    )
