from __future__ import annotations
import json,os
from pathlib import Path
from .models import IncrementalAnalysisPlan
class IncrementalStateStore:
    SCHEMA_VERSION=1
    def save(self,plan:IncrementalAnalysisPlan,path:Path):
        path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name(path.name+'.tmp')
        tmp.write_text(json.dumps({'schema_version':1,'changed_files':[str(x) for x in plan.changed_files],'removed_files':[str(x) for x in plan.removed_files],'directly_changed_symbols':[str(x) for x in plan.directly_changed_symbols],'impacted_symbols':[str(x) for x in plan.impacted_symbols],'files_to_analyze':[str(x) for x in plan.files_to_analyze]},indent=2,sort_keys=True),encoding='utf-8');os.replace(tmp,path)
