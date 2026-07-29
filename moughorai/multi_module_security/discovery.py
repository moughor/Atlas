from __future__ import annotations
from pathlib import Path
import re
from moughorai.java_security import JavaSourceUnit
from .models import ModuleDescriptor, ModuleKind

class ModuleDiscovery:
    _artifact=re.compile(r'<artifactId>\s*([^<]+)\s*</artifactId>')
    _module=re.compile(r'<module>\s*([^<]+)\s*</module>')
    _gradle_include=re.compile(r"include\s+(.+)")
    def discover(self, root: str|Path) -> tuple[ModuleDescriptor,...]:
        base=Path(root)
        if not base.exists(): raise FileNotFoundError(base)
        roots=set()
        for p in base.rglob('pom.xml'): roots.add(p.parent)
        for pattern in ('build.gradle','build.gradle.kts'):
            for p in base.rglob(pattern): roots.add(p.parent)
        if not roots: roots.add(base)
        descriptors=[]
        known_names={r:self._name(r) for r in roots}
        coordinate_to_name={}
        for r,n in known_names.items(): coordinate_to_name[n]=n
        for r in sorted(roots,key=lambda p:str(p).casefold()):
            kind=ModuleKind.MAVEN if (r/'pom.xml').exists() else ModuleKind.GRADLE if ((r/'build.gradle').exists() or (r/'build.gradle.kts').exists()) else ModuleKind.PLAIN
            name=known_names[r]; deps=self._dependencies(r,kind,coordinate_to_name)
            sources=tuple(JavaSourceUnit(str(p.relative_to(base)).replace('\\','/'),p.read_text(encoding='utf-8')) for p in sorted(r.rglob('*.java')) if not any(parent in roots and parent!=r for parent in p.parents))
            descriptors.append(ModuleDescriptor(name,str(r.relative_to(base)).replace('\\','/') or '.',kind,deps,sources,name))
        return tuple(sorted(descriptors,key=lambda m:m.name.casefold()))
    def _name(self,root:Path)->str:
        pom=root/'pom.xml'
        if pom.exists():
            m=self._artifact.search(pom.read_text(encoding='utf-8'))
            if m:return m.group(1).strip()
        return root.name or 'root'
    def _dependencies(self,root:Path,kind:ModuleKind,known)->tuple[str,...]:
        deps=set()
        if kind==ModuleKind.MAVEN:
            text=(root/'pom.xml').read_text(encoding='utf-8')
            artifacts=self._artifact.findall(text)
            own=self._name(root)
            deps.update(a.strip() for a in artifacts if a.strip()!=own and a.strip() in known)
            deps.update(Path(m.strip()).name for m in self._module.findall(text))
        elif kind==ModuleKind.GRADLE:
            files=[p for p in (root/'build.gradle',root/'build.gradle.kts',root/'settings.gradle',root/'settings.gradle.kts') if p.exists()]
            text='\n'.join(p.read_text(encoding='utf-8') for p in files)
            deps.update(re.findall(r'project\(["\']:(.*?)["\']\)',text))
            for line in text.splitlines():
                if 'include' in line:
                    deps.update(x.strip(" '\":") for x in re.findall(r"['\"]:([^'\"]+)['\"]",line))
        return tuple(sorted((d for d in deps if d), key=str.casefold))
