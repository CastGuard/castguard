"""Generate or verify the editable report and its value-to-source evidence index."""
from pathlib import Path
from hashlib import sha256
import argparse,json,re
from report_evidence import collect,fill,sha
ROOT=Path(__file__).resolve().parent

def build(root=ROOT,check=False):
    template=root/'docs/REPORT_DRAFT_TEMPLATE.md'; out=root/'reports/submission_draft'
    facts=collect(root); source=template.read_text(encoding='utf-8'); used=sorted(set(re.findall(r'\{\{([A-Z0-9_]+)\}\}',source)))
    content=fill(source,facts)
    index={'source_template':'docs/REPORT_DRAFT_TEMPLATE.md','template_sha256':sha(template),
       'report_sha256':sha256(content.encode('utf-8')).hexdigest(),'referenced_metric_count':len(used),
       'metrics':{k:facts[k] for k in used},'scope':'Frozen historical results and development queue; no new training or independent test',
       'rubric_weights_authority':'unresolved: task 35/15 versus template 40/10'}
    links='# 수치별 근거 파일\n\n보고서의 같은 키는 같은 원천·선택식·표시 단위를 사용한다. 전체 SHA-256은 evidence_index.json에 있다.\n\n| 근거 키 | 표시값 | 단위 | 원천 | 선택식 |\n|---|---|---|---|---|\n'
    for key in used:
        f=facts[key]
        links+=f"| {key} | {f['display']} | {f['unit']} | [{f['source']}](../../{f['source']}) | {f['selector']} |\n"
    if check:
        assert (out/'CastGuard_report_draft.md').read_text(encoding='utf-8')==content,'Report diverged from evidence-bound template'
        assert json.loads((out/'evidence_index.json').read_text(encoding='utf-8'))==index,'Metric index mismatch'
        assert (out/'EVIDENCE_LINKS.md').read_text(encoding='utf-8')==links,'Evidence links mismatch'
    else:
        out.mkdir(parents=True,exist_ok=True)
        (out/'CastGuard_report_draft.md').write_text(content,encoding='utf-8')
        (out/'evidence_index.json').write_text(json.dumps(index,ensure_ascii=False,indent=2),encoding='utf-8')
        (out/'EVIDENCE_LINKS.md').write_text(links,encoding='utf-8')
    return {'metrics_bound':len(used),'source_files':len({facts[k]['source'] for k in used}),'check':check}

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--check',action='store_true'); a=p.parse_args();print(json.dumps(build(check=a.check)))
