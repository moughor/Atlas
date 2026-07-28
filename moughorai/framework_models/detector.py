from __future__ import annotations
from moughorai.java_security import JavaSourceUnit
from .catalog import PROFILES
from .models import FrameworkDetection

class FrameworkDetector:
    def detect(self, units: tuple[JavaSourceUnit, ...] | list[JavaSourceUnit], configurations: tuple[tuple[str,str], ...]=()) -> FrameworkDetection:
        haystacks=[(u.path,u.source) for u in units]+list(configurations)
        found=[]; evidence=[]
        for profile in PROFILES:
            hits=[]
            for path,text in haystacks:
                for marker in profile.markers:
                    if marker in text:
                        hits.append((path,marker)); break
            if hits:
                found.append(profile.framework)
                evidence.extend((profile.framework.value,f'{p}:{m}') for p,m in hits)
        return FrameworkDetection(tuple(sorted(found,key=lambda f:f.value)),tuple(sorted(set(evidence))))
