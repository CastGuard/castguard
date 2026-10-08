"""Verify the reviewed candidate and publish it locally with fresh manifests."""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import hashlib
import json
import re
import shutil
import zipfile
from html.parser import HTMLParser

from pypdf import PdfReader
from PIL import Image, ImageChops

ROOT=Path(__file__).resolve().parent
BUILD=ROOT/'reports/oct08_submission'
OUT=BUILD/'candidate'
BASE=BUILD/'source_staging/CastGuard'


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,data):p.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')


def main():
    # Only presentation/report prose changed after the successful unpacked smoke checks.
    for relative in ['build_oct08_submission.py','reports/oct08_submission/CastGuard_report.md']:
        shutil.copy2(ROOT/relative,BASE/relative)
    prior=BUILD/'unpacked/CastGuard'
    unchanged=0
    for p in prior.rglob('*'):
        if p.is_file() and p.suffix in ['.py','.joblib','.json','.parquet','.csv'] and '__pycache__' not in p.parts:
            rel=p.relative_to(prior)
            if rel.as_posix() in ['build_oct08_submission.py','PACKAGE_MANIFEST.json','verification_demo.json']:continue
            q=BASE/rel
            if q.exists():
                assert sha(p)==sha(q),rel
                unchanged+=1
    manifest=[{'path':p.relative_to(BASE).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(BASE.rglob('*')) if p.is_file() and p.name!='PACKAGE_MANIFEST.json']
    write(BASE/'PACKAGE_MANIFEST.json',{'created_at':datetime.now(timezone.utc).isoformat(),'files':manifest,'scope':'JH base plus four-combination study and reproduced team add evidence'})
    with zipfile.ZipFile(OUT/'CastGuard_source.zip','w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(BASE.rglob('*')):
            if p.is_file():z.write(p,'CastGuard/'+p.relative_to(BASE).as_posix())
    with zipfile.ZipFile(OUT/'CastGuard_source.zip') as z:
        assert z.testzip() is None
        for item in manifest:
            data=z.read('CastGuard/'+item['path'])
            assert hashlib.sha256(data).hexdigest()==item['sha256']
            if Path(item['path']).suffix in ['.py','.md','.json','.txt','.html','.toml']:
                assert not re.search(r'C:[/\\]Users[/\\]|/home/ozingmw',data.decode('utf-8-sig')),item['path']
    report=PdfReader(OUT/'CastGuard_report.pdf');deck=PdfReader(OUT/'CastGuard_presentation.pdf')
    assert len(report.pages)==18 and len(deck.pages)==19
    text='\n'.join(p.extract_text() for p in report.pages)
    for token in ['0.3845','0.7378','0.3263','0.3232','0.3228','2.29%','35점','15점']:
        assert token in text,token
    for n in range(1,7):assert f'제{n}장' in text
    assert '서명' in report.pages[16].extract_text()
    survey=Image.open(ROOT/'docs/설문조사완료.png').convert('RGB')
    assert sha(ROOT/'docs/설문조사완료.png')==sha(OUT/'설문조사완료.png')
    assert any(im.image.size==survey.size and ImageChops.difference(im.image.convert('RGB'),survey).getbbox() is None for im in report.pages[-1].images)
    native=json.loads((BUILD/'slides/render_receipt.json').read_text(encoding='utf-8-sig'))
    assert native['slides']==19 and native['overflow_count']==0
    finalizer=json.loads((BUILD/'deck_build/validation-v2.json').read_text())
    assert finalizer['finalSha256']==sha(OUT/'CastGuard_presentation.pptx')
    class Audit(HTMLParser):
        def __init__(self):super().__init__();self.tags={};self.external=[]
        def handle_starttag(self,tag,attrs):
            self.tags[tag]=self.tags.get(tag,0)+1
            for k,v in attrs:
                if k in ['src','href'] and v and v.startswith(('http:','https:')):self.external.append(v)
    html=Audit();html.feed((OUT/'CastGuard_demo.html').read_text(encoding='utf-8'))
    assert html.tags.get('article')==11 and html.tags.get('details')==11 and not html.external and not html.tags.get('script')
    receipt={'checked_at':datetime.now(timezone(timedelta(hours=9))).isoformat(),
        'status':'locally verified submission candidate; actual signatures and portal receipt pending',
        'report_pages':18,'presentation_slides':19,'visual_inspection':'all 18 report pages and 19 native PowerPoint slide PNGs inspected',
        'powerpoint_text_overflow':0,'survey_original_bytes_and_embedded_pixels_preserved':True,
        'source_zip_files':len(manifest)+1,'source_manifest_hashes_verified':len(manifest),
        'repository_tests':{'passed':418,'failed':0},'unpacked_package_tests':{'passed':20,'failed':0},'unpacked_cli_records':11,
        'scientific_files_unchanged_since_unpacked_smoke':unchanged,
        'fusion_verification':json.loads((ROOT/'reports/oct08_fusion/verification.json').read_text()),
        'team_replay':json.loads((ROOT/'reports/oct08_team_replay/verification.json').read_text()),
        'demo':{'records':11,'static_content_verified':True,'browser_interaction_verified':False},
        'not_verified':['new independent future performance','field arrival times and physical variable equivalence','actual field cost benefit','actual signatures','portal submission'],
        'preserved_before':'reports/oct08_submission/before/submission',
        'artifacts':[{'file':p.name,'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(OUT.iterdir()) if p.is_file() and p.name not in ['README.md','VERIFICATION.json','CHECKSUMS.sha256']]}
    write(BUILD/'final_checks.json',receipt);write(OUT/'VERIFICATION.json',receipt)
    readme='''# CastGuard 제출 후보 · 10/8 팀 연구 통합본

팀명: **RE제조부터시작하는이세계생활** · 팀장 **정가현** · 팀원 **신종훈**

| 파일 | 내용 |
| --- | --- |
| [CastGuard_report.pdf](CastGuard_report.pdf) | 공식 6장 구조, 18쪽. 성과 중심 요약·네 조합 실험·팀 Gate/유형별 연구·설문 원본 |
| [CastGuard_presentation.pdf](CastGuard_presentation.pdf) | 19장 발표 PDF |
| [CastGuard_presentation.pptx](CastGuard_presentation.pptx) | 편집 가능한 19장 발표 자료 |
| [CastGuard_source.zip](CastGuard_source.zip) | 291파일. JH 기반 코드·원본·고정 분할·모델·새 실험·팀 add 근거·재현 절차 |
| [CastGuard_demo.html](CastGuard_demo.html) | 기존 판독 모델의 11개 실제 입력·설명·지원 경고 및 10/8 안내 |
| [설문조사완료.png](설문조사완료.png) | 제공 원본 바이트 보존. 보고서 18쪽에도 삽입 |
| [VERIFICATION.json](VERIFICATION.json) | 이번 실행·재현·렌더·패키지 확인과 미검증 범위 |
| [CHECKSUMS.sha256](CHECKSUMS.sha256) | 이 묶음의 SHA-256 |

## 이번에 반영한 내용

- 같은 구간 재사용 test에서 상위 277/1,387 검사로 불량 117/272(43.01%) 포착, 무작위 기대값 대비 약 2.15배를 먼저 설명합니다. 현재 판독 모델은 AUC 0.7378/AP 0.3845의 기존 S_FB/logistic입니다.
- #42, #42+#41, #42+#40, #42+#41+#40을 같은 RF·로지스틱/3 seed/고정 분할에서 비교했습니다. 피드백 유무도 분리했습니다. RF 주 표의 test AP는 0.3263/0.3248/0.3232/0.3228이며 추가 입력의 사전 개선 기준은 미달했습니다.
- 팀 add 작업의 Gate와 5개 불량 유형별 결과를 실제 재현해 통합했습니다. Gate의 같은 구간 탐지 8개/관측 9개/전체 10개, 정상 FPR 2.29%를 미래 실패와 함께 표시합니다. 다른 모집단의 기존 Gate와 직접 우열을 비교하지 않습니다.
- 공정 간 변수 대응은 가정이며 인과 원인·현장 개선·전이 성공으로 확대하지 않습니다. 사후 순위검사, validation 임계값 및 기존 causal queue를 구분합니다.

## 확인한 근거

전체 418개 검사, 별도 ZIP 20개 검사 및 11건 CLI 판독이 통과했습니다. 새 실험의 480개 평가 그룹은 재학습 재현 시 최대 차이 0, 기존 JH와 공통인 78개 그룹도 차이 0입니다. add Gate 22개 표 행과 유형별 5개 행은 기존 반올림 표와 일치했습니다. 이는 계산 재현이며 독립 성능 검증은 아닙니다.

보고서 18쪽·발표 19장 화면을 확인했고 PowerPoint 텍스트 넘침은 0입니다. 설문 원본/삽입 픽셀과 ZIP 명세 해시를 대조했습니다. HTML은 정적 내용·CLI를 확인했으며 팀 브라우저에서 직접 펼침/표시 확인은 아직 필요합니다.

## 참가팀의 실제 제출 단계

1. **보고서 17쪽의 두 사람 서명**을 실제로 완료하고 서명본을 확인합니다. 서명 후에는 PDF 해시가 바뀌므로 서명본의 SHA-256을 별도로 기록합니다.
2. 보고서 PDF, 소스 ZIP, 발표 PDF/PPTX와 설문 첨부를 확인합니다. 예측 파일은 ZIP 안 predictions/test_predictions.csv에서 바로 찾을 수 있습니다.
3. 보존 공고 기준 **10/8 23:59 KST 이전**에 포털 접수하고 접수 증빙을 보관합니다. 실제 제출은 아직 수행하지 않았습니다.

이전 10/6 제출 후보는 reports/oct08_submission/before/submission에 그대로 보존했습니다. 현재 파일의 검수 시각과 해시는 VERIFICATION.json을 기준으로 확인하십시오. 서명·현장 효과·실제 접수는 파일 완성으로 대체하지 않습니다.
'''
    (OUT/'README.md').write_text(readme,encoding='utf-8')
    (OUT/'CHECKSUMS.sha256').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in sorted(OUT.iterdir()) if p.is_file() and p.name!='CHECKSUMS.sha256'),encoding='utf-8')
    # Local delivery only. Old submission files have been preserved byte-for-byte.
    for p in OUT.iterdir():
        if p.is_file():shutil.copy2(p,ROOT/'submission'/p.name)
    for p in OUT.iterdir():
        if p.is_file():assert sha(p)==sha(ROOT/'submission'/p.name)
    print(json.dumps({'passed':True,'source_files':len(manifest)+1,'report_pages':18,'slides':19,'local_delivery':True}))


if __name__=='__main__':main()
