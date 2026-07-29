from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Callable, Iterable

from .models import PolicyPack, PolicyPackError
from .registry import PolicyPackRegistry
from .resolution import SemanticVersion, VersionConstraint, pack_digest
from .serialization import pack_to_dict


@dataclass(frozen=True, slots=True)
class LifecycleEvent:
    sequence: int
    action: str
    pack: str
    version: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "action": self.action,
            "pack": self.pack,
            "version": self.version,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class LifecycleReport:
    action: str
    pack: str
    previous_version: str = ""
    current_version: str = ""
    changed: bool = False
    rolled_back: bool = False
    events: tuple[LifecycleEvent, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "pack": self.pack,
            "previous_version": self.previous_version,
            "current_version": self.current_version,
            "changed": self.changed,
            "rolled_back": self.rolled_back,
            "events": [event.to_dict() for event in self.events],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


class PolicyPackLifecycleManager:
    """Transactional lifecycle manager for versioned policy packs.

    The manager owns an installed-pack set and an active-pack set. Mutating
    operations validate the complete resulting state before committing it.
    """

    FORMAT_VERSION = 1

    def __init__(
        self,
        packs: Iterable[PolicyPack] = (),
        *,
        active: Iterable[str] | None = None,
        engine_version: str = "1.0.0",
        validator: Callable[[tuple[PolicyPack, ...]], None] | None = None,
    ):
        SemanticVersion.parse(engine_version)
        self.engine_version = engine_version
        self._validator = validator
        self._packs: dict[str, PolicyPack] = {}
        for pack in packs:
            if pack.name in self._packs:
                raise PolicyPackError(f"duplicate policy pack name: {pack.name}")
            self._packs[pack.name] = pack
        self._active = set(active if active is not None else self._packs)
        unknown = self._active.difference(self._packs)
        if unknown:
            raise PolicyPackError(f"active policy pack is not installed: {sorted(unknown)[0]}")
        self._events: list[LifecycleEvent] = []
        self._validate_state(self._packs, self._active)

    @property
    def installed(self) -> tuple[PolicyPack, ...]:
        return tuple(sorted(self._packs.values(), key=lambda p: (p.name, SemanticVersion.parse(p.version))))

    @property
    def active_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._active))

    @property
    def events(self) -> tuple[LifecycleEvent, ...]:
        return tuple(self._events)

    def get(self, name: str) -> PolicyPack:
        try:
            return self._packs[name]
        except KeyError as exc:
            raise PolicyPackError(f"policy pack is not installed: {name}") from exc

    def registry(self) -> PolicyPackRegistry:
        return PolicyPackRegistry(tuple(self.get(name) for name in self.active_names))

    def install(self, pack: PolicyPack, *, activate: bool = True, replace: bool = False) -> LifecycleReport:
        previous = self._packs.get(pack.name)
        if previous is not None and not replace:
            raise PolicyPackError(f"policy pack is already installed: {pack.name}")
        if previous is not None and previous == pack:
            return self._report("install", pack.name, previous.version, pack.version, False, False, ())

        candidate = dict(self._packs)
        candidate[pack.name] = pack
        active = set(self._active)
        if activate:
            active.add(pack.name)
        self._validate_state(candidate, active)
        self._packs, self._active = candidate, active
        event = self._record("installed" if previous is None else "replaced", pack)
        return self._report("install", pack.name, previous.version if previous else "", pack.version, True, False, (event,))

    def activate(self, name: str) -> LifecycleReport:
        pack = self.get(name)
        if name in self._active:
            return self._report("activate", name, pack.version, pack.version, False, False, ())
        active = set(self._active)
        active.add(name)
        self._validate_state(self._packs, active)
        self._active = active
        event = self._record("activated", pack)
        return self._report("activate", name, pack.version, pack.version, True, False, (event,))

    def deactivate(self, name: str, *, cascade: bool = False) -> LifecycleReport:
        pack = self.get(name)
        if name not in self._active:
            return self._report("deactivate", name, pack.version, pack.version, False, False, ())
        dependents = self._active_dependents(name)
        if dependents and not cascade:
            raise PolicyPackError(f"cannot deactivate {name}; active dependents: {', '.join(dependents)}")
        targets = {name, *dependents} if cascade else {name}
        self._active.difference_update(targets)
        events = tuple(self._record("deactivated", self._packs[target], detail=f"cascade_from={name}" if target != name else "") for target in sorted(targets, reverse=True))
        return self._report("deactivate", name, pack.version, pack.version, True, False, events)

    def uninstall(self, name: str, *, cascade: bool = False) -> LifecycleReport:
        pack = self.get(name)
        dependents = self._installed_dependents(name)
        if dependents and not cascade:
            raise PolicyPackError(f"cannot uninstall {name}; installed dependents: {', '.join(dependents)}")
        targets = {name, *dependents} if cascade else {name}
        candidate = {key: value for key, value in self._packs.items() if key not in targets}
        active = self._active.difference(targets)
        self._validate_state(candidate, active)
        self._packs, self._active = candidate, active
        events = tuple(self._record("uninstalled", self._packs.get(target, pack) if target == name else pack, detail=f"removed={target}") for target in sorted(targets, reverse=True))
        return self._report("uninstall", name, pack.version, "", True, False, events)

    def upgrade(self, pack: PolicyPack, *, allow_downgrade: bool = False) -> LifecycleReport:
        previous = self.get(pack.name)
        old_version = SemanticVersion.parse(previous.version)
        new_version = SemanticVersion.parse(pack.version)
        if new_version == old_version:
            if pack_digest(previous) == pack_digest(pack):
                return self._report("upgrade", pack.name, previous.version, pack.version, False, False, ())
            raise PolicyPackError("same-version policy pack replacement is not allowed")
        if new_version < old_version and not allow_downgrade:
            raise PolicyPackError(f"policy pack downgrade is not allowed: {previous.version} -> {pack.version}")

        old_packs, old_active = dict(self._packs), set(self._active)
        candidate = dict(self._packs)
        candidate[pack.name] = pack
        try:
            self._validate_state(candidate, old_active)
            self._packs = candidate
            event = self._record("upgraded" if new_version > old_version else "downgraded", pack, f"from={previous.version}")
            return self._report("upgrade", pack.name, previous.version, pack.version, True, False, (event,))
        except Exception:
            self._packs, self._active = old_packs, old_active
            event = self._record("rollback", previous, f"attempted={pack.version}")
            return self._report("upgrade", pack.name, previous.version, previous.version, False, True, (event,))

    def export_state(self) -> str:
        data = {
            "format_version": self.FORMAT_VERSION,
            "engine_version": self.engine_version,
            "active": list(self.active_names),
            "packs": [pack_to_dict(pack) for pack in self.installed],
        }
        return json.dumps(data, indent=2, sort_keys=True) + "\n"

    @classmethod
    def import_state(cls, text: str, *, loader, validator=None) -> "PolicyPackLifecycleManager":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PolicyPackError(f"invalid lifecycle state JSON: {exc.msg}") from exc
        if data.get("format_version") != cls.FORMAT_VERSION:
            raise PolicyPackError("unsupported lifecycle state format_version")
        packs = tuple(loader.load_mapping(item, "<lifecycle-state>") for item in data.get("packs", []))
        return cls(packs, active=data.get("active", []), engine_version=data.get("engine_version", "1.0.0"), validator=validator)

    def _validate_state(self, packs: dict[str, PolicyPack], active: set[str]) -> None:
        for pack in packs.values():
            engine_constraint = dict(pack.metadata).get("engine_api", "*")
            if not VersionConstraint(engine_constraint).matches(self.engine_version):
                raise PolicyPackError(f"{pack.name} requires engine {engine_constraint}, found {self.engine_version}")
        active_packs = tuple(packs[name] for name in sorted(active))
        PolicyPackRegistry(active_packs).resolved_packs()
        seen: dict[str, str] = {}
        for pack in active_packs:
            for policy in pack.policies:
                owner = seen.get(policy.rule_id)
                if owner is not None:
                    raise PolicyPackError(f"rule conflict: {policy.rule_id} provided by {owner} and {pack.name}")
                seen[policy.rule_id] = pack.name
        if self._validator is not None:
            self._validator(active_packs)

    def _active_dependents(self, name: str) -> tuple[str, ...]:
        return self._dependents(name, self._active)

    def _installed_dependents(self, name: str) -> tuple[str, ...]:
        return self._dependents(name, set(self._packs))

    def _dependents(self, name: str, population: set[str]) -> tuple[str, ...]:
        result: set[str] = set()
        changed = True
        while changed:
            changed = False
            for candidate in sorted(population):
                if candidate == name or candidate in result:
                    continue
                deps = {dep.name for dep in self._packs[candidate].dependencies if not dep.optional}
                if name in deps or deps.intersection(result):
                    result.add(candidate)
                    changed = True
        return tuple(sorted(result))

    def _record(self, action: str, pack: PolicyPack, detail: str = "") -> LifecycleEvent:
        event = LifecycleEvent(len(self._events) + 1, action, pack.name, pack.version, detail)
        self._events.append(event)
        return event

    @staticmethod
    def _report(action, pack, previous, current, changed, rolled_back, events):
        return LifecycleReport(action, pack, previous, current, changed, rolled_back, tuple(events))
