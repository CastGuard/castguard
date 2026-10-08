"""Publish the 10/8 second candidate: extended report + source ZIP with the 10/8 search studies.

Presentation PDF/PPTX, demo HTML and survey PNG are carried over unchanged from the verified
21:01 candidate. The previous submission folder is preserved byte-for-byte first.
"""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import hashlib
import json
import re
import shutil
import zipfile

from pypdf import PdfReader
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parent
PREV_BUILD = ROOT / 'reports/oct08_submission'
BUILD = ROOT / 'reports/oct08b_submission'
OUT = BUILD / 'candidate'
STAGE = BUILD / 'source_staging'
BASE = STAGE / 'CastGuard'
RESULT_DIRS = ['reports/oct08_model_search', 'reports/oct08_crossed_search', 'reports/oct08_window_search']
CODE = ['castguard/model_search.py', 'castguard/crossed_search.py', 'castguard/crossed_reader.py', 'castguard/search_reader.py',
        'castguard/window_search.py', 'configs/oct08_model_search.json', 'configs/oct08_model_refine.json', 'configs/oct08_crossed_search.json',
        'docs/OCT08_MODEL_SEARCH_PROTOCOL.md', 'docs/OCT08_MODEL_REFINE_PROTOCOL.md', 'docs/OCT08_CROSSED_SEARCH_PROTOCOL.md',
        'tests/test_model_search.py', 'tests/test_crossed_search.py', 'refine_model_search.py', 'analyze_model_search.py',
        'analyze_crossed_search.py', 'verify_model_search.py', 'verify_crossed_search.py', 'requirements-model-search.txt',
        'build_oct08b_report.py', 'reports/oct08b_submission/CastGuard_report.md']


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write(p, data):
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    before = BUILD / 'before/submission'
    if not before.exists():
        shutil.copytree(ROOT / 'submission', before)
        for p in (ROOT / 'submission').iterdir():
            assert sha(p) == sha(before / p.name)
    # Re-runs: the 21:01 candidate must still match the preserved copy.
    prev_checks = json.loads((PREV_BUILD / 'final_checks.json').read_text(encoding='utf-8'))
    for a in prev_checks['artifacts']:
        assert sha(before / a['file']) == a['sha256'], a['file']
    if STAGE.exists():
        shutil.rmtree(STAGE)
    shutil.copytree(PREV_BUILD / 'source_staging/CastGuard', BASE, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    prior_manifest = {x['path']: x['sha256'] for x in json.loads((BASE / 'PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))['files']}

    def copy(rel):
        src = ROOT / rel; dst = BASE / rel
        dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(src, dst)
    for rel in CODE:
        copy(rel)
    added = 0
    for folder in RESULT_DIRS:
        for p in (ROOT / folder).rglob('*'):
            if p.is_file() and 'candidates' not in p.parts and p.suffix not in ['.joblib', '.log', '.pyc'] and '__pycache__' not in p.parts:
                copy(p.relative_to(ROOT).as_posix()); added += 1
    # Scientific files from the prior package must be unchanged.
    unchanged = 0
    for path, digest in prior_manifest.items():
        q = BASE / path
        if q.exists() and Path(path).suffix in ['.py', '.joblib', '.json', '.parquet', '.csv'] and path not in ['PACKAGE_MANIFEST.json']:
            if sha(q) != digest:
                raise AssertionError(path)
            unchanged += 1
    manifest = [{'path': p.relative_to(BASE).as_posix(), 'bytes': p.stat().st_size, 'sha256': sha(p)} for p in sorted(BASE.rglob('*')) if p.is_file() and p.name != 'PACKAGE_MANIFEST.json']
    write(BASE / 'PACKAGE_MANIFEST.json', {'created_at': datetime.now(timezone.utc).isoformat(), 'files': manifest,
          'scope': 'JH base + four-combination study + team evidence + 10/8 model search, crossed model x data study and time-window study (summaries, metrics, seals, predictions; large checkpoints excluded)'})
    OUT.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT / 'CastGuard_source.zip', 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(BASE.rglob('*')):
            if p.is_file():
                z.write(p, 'CastGuard/' + p.relative_to(BASE).as_posix())
    with zipfile.ZipFile(OUT / 'CastGuard_source.zip') as z:
        assert z.testzip() is None
        for item in manifest:
            data = z.read('CastGuard/' + item['path'])
            assert hashlib.sha256(data).hexdigest() == item['sha256']
            if Path(item['path']).suffix in ['.py', '.md', '.json', '.txt', '.html', '.toml']:
                assert not re.search(r'C:[/\\]Users[/\\]|/home/ozingmw', data.decode('utf-8-sig')), item['path']
    # Carry over unchanged artefacts; the deck is rebuilt (20 slides) by build_b.mjs + export_oct08b_submission.ps1.
    for name in ['CastGuard_demo.html', '설문조사완료.png']:
        shutil.copy2(before / name, OUT / name)
        assert sha(OUT / name) == sha(before / name)
    finalizer = json.loads((BUILD / 'deck_build/validation-v2.json').read_text(encoding='utf-8'))
    assert finalizer['finalSha256'] == sha(OUT / 'CastGuard_presentation.pptx') and finalizer['packageIntegrity']['slide_count'] == 20
    native = json.loads((BUILD / 'slides/render_receipt.json').read_text(encoding='utf-8-sig'))
    assert native['slides'] == 20 and native['overflow_count'] == 0
    report = PdfReader(OUT / 'CastGuard_report.pdf'); deck = PdfReader(OUT / 'CastGuard_presentation.pdf')
    pages = len(report.pages)
    text = '\n'.join(p.extract_text() for p in report.pages)
    for token in ['0.3845', '0.7378', '0.3263', '0.3232', '0.3228', '2.29%', '35점', '15점', '0.3713', '2.4 모델 탐색', '2.5 시간 창', 'mean_all']:
        assert token in text, token
    for n in range(1, 7):
        assert f'제{n}장' in text
    signature_page = next(i for i, p in enumerate(report.pages) if '서명' in p.extract_text() and '팀장' in p.extract_text())
    survey = Image.open(ROOT / 'docs/설문조사완료.png').convert('RGB')
    assert sha(ROOT / 'docs/설문조사완료.png') == sha(OUT / '설문조사완료.png')
    assert any(im.image.size == survey.size and ImageChops.difference(im.image.convert('RGB'), survey).getbbox() is None for im in report.pages[-1].images)
    assert len(deck.pages) == 20
    receipt = {'checked_at': datetime.now(timezone(timedelta(hours=9))).isoformat(),
        'status': 'locally verified second 10/8 candidate; actual signatures and portal receipt pending',
        'report_pages': pages, 'signature_page': signature_page + 1, 'presentation_slides': 20,
        'presentation_rebuilt': 'one slide added (model x data crossed comparison, time-window result); finalizer pass, PowerPoint text overflow 0',
        'demo_unchanged_from_21_01_candidate': True,
        'report_visual_inspection': 'text extraction and page structure checks; full page-image inspection of the new pages not repeated under deadline',
        'survey_original_bytes_and_embedded_pixels_preserved': True,
        'source_zip_files': len(manifest) + 1, 'source_manifest_hashes_verified': len(manifest),
        'prior_package_scientific_files_unchanged': unchanged, 'result_files_added': added,
        'studies_added': {'model_search': json.loads((ROOT / 'reports/oct08_model_search/summary.json').read_text(encoding='utf-8'))['adoption_criteria_met'],
                          'crossed_search_locked_criteria_passes': json.loads((ROOT / 'reports/oct08_crossed_search/summary.json').read_text(encoding='utf-8'))['locked_setting_validation_criteria_passes'],
                          'window_search_selection': json.loads((ROOT / 'reports/oct08_window_search/selection_seal.json').read_text(encoding='utf-8'))},
        'final_model_unchanged': 'S_FB logistic reader retained; no reselection on test',
        'not_verified': ['new independent future performance', 'field arrival times and physical variable equivalence', 'actual field cost benefit', 'actual signatures', 'portal submission', 'browser interaction of demo HTML'],
        'preserved_before': 'reports/oct08b_submission/before/submission',
        'artifacts': [{'file': p.name, 'bytes': p.stat().st_size, 'sha256': sha(p)} for p in sorted(OUT.iterdir()) if p.is_file() and p.name not in ['README.md', 'VERIFICATION.json', 'CHECKSUMS.sha256']]}
    write(BUILD / 'final_checks.json', receipt); write(OUT / 'VERIFICATION.json', receipt)
    readme = f'''# CastGuard 제출 후보 · 10/8 2차(모델 탐색·교차 비교·시간 창 집계 반영)

팀명: **RE제조부터시작하는이세계생활** · 팀장 **정가현** · 팀원 **신종훈**

| 파일 | 내용 |
| --- | --- |
| [CastGuard_report.pdf](CastGuard_report.pdf) | 공식 6장 구조, {pages}쪽. 2.5–2.7절에 7개 모델군 탐색·모델×데이터 교차 비교·시간 창 집계 제거실험·최종 모델 선정 근거 추가. 서명란 {signature_page + 1}쪽, 설문 원본 마지막 쪽 |
| [CastGuard_presentation.pdf](CastGuard_presentation.pdf) | 20장 발표 PDF. 13장에 모델군×데이터 조합 교차 비교·시간 창 결과 슬라이드 추가 |
| [CastGuard_presentation.pptx](CastGuard_presentation.pptx) | 편집 가능한 20장 발표 자료(PowerPoint 텍스트 넘침 0) |
| [CastGuard_source.zip](CastGuard_source.zip) | {len(manifest) + 1}파일. 기존 묶음 + 10/8 모델 탐색·교차 비교·시간 창 실험의 코드·설정·사전 계획·검증·지표·선택 봉인·예측 |
| [CastGuard_demo.html](CastGuard_demo.html) | 기존 판독 모델의 11개 실제 입력·설명·지원 경고(동일) |
| [설문조사완료.png](설문조사완료.png) | 제공 원본 바이트 보존 |
| [VERIFICATION.json](VERIFICATION.json) | 이번 검수 결과와 미검증 범위 |
| [CHECKSUMS.sha256](CHECKSUMS.sha256) | 이 묶음의 SHA-256 |

## 이번에 반영한 내용

- 2.5절: XGBoost·CatBoost·LightGBM·MLP·TabM 272설정·53앙상블을 train/validation만으로 선택한 결과. validation 선택 mean_all의 재사용 test AP 0.3849/AUC 0.7401/포착 122건 vs 기존 0.3845/0.7378/117건. AP 차이 95% 범위가 0을 포함하고 정상 FPR이 9.51%→13.27%로 늘어 기존 판독기를 유지.
- 2.6절: 7개 모델군 × 네 데이터 조합(피드백 유무) 848후보 교차 비교. #42 단독 로지스틱 B0(AP 0.3713/114건) 대비, validation으로 선택한 모든 조합의 후보가 test에서 B0보다 낮음. 고정 설정 데이터 추가 42비교의 사전 기준 통과 0건. MLP+#42+#41의 test AP 0.3953은 사후 관측으로 명시.
- 2.7절: 공고 권장 시간 창 집계(#41 직전 5/20 Shot, 현재 제외)를 S에 붙인 제거실험 180 fit. validation 기준을 유일하게 통과한 LightGBM+SW가 test에서 역전(AP 0.3234→0.3019). 최종 모델 선정 근거를 표로 정리.
- 발표 자료는 13장(교차 비교·시간 창 결과) 1장을 추가해 20장이 됐고 나머지 슬라이드는 21:01 후보와 같습니다. 데모·설문은 동일합니다.

## 참가팀의 실제 제출 단계

1. 보고서 {signature_page + 1}쪽의 두 사람 서명을 실제로 완료하고, 서명본의 SHA-256을 별도 기록합니다.
2. 보고서 PDF, 소스 ZIP, 발표 PDF/PPTX, 설문 첨부를 확인합니다. 예측 파일은 ZIP 안 predictions/test_predictions.csv입니다.
3. **10/8 23:59 KST 이전**에 포털 접수하고 접수 증빙을 보관합니다. 실제 제출은 아직 수행하지 않았습니다.

이전 21:01 후보는 reports/oct08b_submission/before/submission에 보존했습니다. 시간 부족으로 새 보고서 쪽의 화면 이미지 검수는 반복하지 않았고 텍스트·구조·설문 삽입만 확인했습니다.
'''
    (OUT / 'README.md').write_text(readme, encoding='utf-8')
    (OUT / 'CHECKSUMS.sha256').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in sorted(OUT.iterdir()) if p.is_file() and p.name != 'CHECKSUMS.sha256'), encoding='utf-8')
    for p in OUT.iterdir():
        if p.is_file():
            shutil.copy2(p, ROOT / 'submission' / p.name)
    for p in OUT.iterdir():
        if p.is_file():
            assert sha(p) == sha(ROOT / 'submission' / p.name)
    print(json.dumps({'passed': True, 'source_files': len(manifest) + 1, 'report_pages': pages, 'signature_page': signature_page + 1, 'result_files_added': added, 'unchanged_prior': unchanged}))


if __name__ == '__main__':
    main()
