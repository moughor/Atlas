from __future__ import annotations
import json
import yaml
from .models import PolicyPack

def pack_to_dict(pack:PolicyPack):
    def matcher(m): return {'pattern':m.pattern,'mode':m.mode.value}
    return {'schema_version':pack.schema_version,'name':pack.name,'version':pack.version,'description':pack.description,'metadata':dict(pack.metadata),'dependencies':[{'name':d.name,'constraint':d.constraint,'optional':d.optional} for d in pack.dependencies],'policies':[{'rule_id':p.rule_id,'title':p.title,'message':p.message,'sources':[matcher(m) for m in p.sources],'sinks':[matcher(m) for m in p.sinks],'sanitizers':[matcher(m) for m in p.sanitizers],'severity':p.severity.value,'confidence':p.confidence.value,'cwe':p.cwe,'owasp':p.owasp,'priority':p.priority,'enabled':p.enabled,'properties':dict(p.properties)} for p in pack.policies]}
def pack_to_json(pack,indent=2): return json.dumps(pack_to_dict(pack),indent=indent,sort_keys=True)+'\n'
def pack_to_yaml(pack): return yaml.safe_dump(pack_to_dict(pack),sort_keys=False,allow_unicode=True)
