"""Curated submission source ZIP; no Git metadata, local paths, or historical scratch artifacts."""
from pathlib import Path
import json,hashlib,shutil,zipfile
from datetime import datetime,timezone
import pandas as pd

ROOT=Path(__file__).resolve().parent
BUILD=ROOT/'reports/oct06_submission'
STAGE=BUILD/'source_staging_v3'
OUT=ROOT/'submission'


def copy(relative):
    source=ROOT/relative;target=STAGE/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)


def main():
    if STAGE.exists():raise FileExistsError('preserve existing stage; choose version explicitly')
    STAGE.mkdir(parents=True)
    for folder in ['castguard','data/raw','data/processed','examples/submission_reader']:
        for p in (ROOT/folder).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc':copy(p.relative_to(ROOT))
    for rel in ['configs/oct06_research.json','configs/oct02.json','docs/OCT06_RESEARCH_PROTOCOL.md','docs/PREPROCESSING.md','docs/SUBMISSION_READER.md',
                'reproduce_submission.py','analyze_oct06.py','prepare_submission_demo.py','verify_oct06.py',
                'build_oct06_submission.py','tests/test_oct06_research.py','tests/test_submission_reader.py',
                'requirements-lock.txt','requirements-review-win-py312.lock','pyproject.toml']:
        copy(rel)
    for p in (ROOT/'reports/oct06_research').iterdir():
        if p.is_file() and p.suffix in ['.csv','.parquet','.json','.html']:
            copy(p.relative_to(ROOT))
    # Include each validation-selected checkpoint for analysis replay; do not ship unsuccessful candidate caches.
    sel=json.loads((ROOT/'reports/oct06_research/selection.json').read_text())
    for s in sel['selections']:
        for seed in [17,29,43]:
            copy(f'reports/oct06_research/models/{s["scheme"]}__{s["fold"]}__{s["representation"]}__{s["model"]}__{seed}/model.joblib')
    gate=json.loads((ROOT/'configs/decision_review.json').read_text(encoding='utf-8'))['checkpoints']['queue-fold3-seed17']['gate']
    copy(gate['path']);(STAGE/'configs/decision_review.json').write_text(json.dumps({'checkpoints':{'queue-fold3-seed17':{'gate':gate}}},ensure_ascii=False,indent=2),encoding='utf-8')
    for rel in ['reports/oct03_round7/group_metrics.csv','reports/oct03_round7/defect_metrics.csv','reports/oct03_round7/paired_uncertainty.csv',
                'reports/oct03_queue_review/pooled_at20.csv','reports/oct02/ablation_summary.csv','reports/oct02/bootstrap_intervals.csv',
                'reports/oct06_submission/CastGuard_report.md','docs/설문조사완료.png']:
        copy(rel)
    pred=pd.read_parquet(ROOT/'reports/oct06_research/selected_predictions.parquet')
    pred[(pred.scheme=='within_run')&(pred.role=='test')&(pred.representation=='S_FB')&(pred.seed==17)].to_csv(STAGE/'research_reader_predictions.csv',index=False,encoding='utf-8-sig')
    # Install exact scientific dependencies without forcing platform-specific document tooling.
    (STAGE/'requirements.txt').write_text('-r requirements-lock.txt\n',encoding='utf-8')
    readme=r'''# CastGuard 제출 소스

팀명: RE제조부터시작하는이세계생활 / 팀장 정가현 / 팀원 신종훈

## 빠른 실행

Windows x64 CPython3.12.14에서 검증한 연구 코드입니다. Python3.12 환경에서 아래 순서로 실행합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q tests
.\.venv\Scripts\python.exe -m castguard.submission_reader --input examples/submission_reader/shots.json --output demo.json --html demo.html
```

출력 경로가 이미 있으면 덮어쓰지 않습니다. `demo.html`을 브라우저에서 열면 실제 위험 점수·개별 기여·적용경고·사람검토 판단과 기존 검사정책 비교를 볼 수 있습니다. 현재/미래 정답은 거절하고 과거 품질 피드백은 동일run의 공정event 기준20개 이상 지난 회신만 허용합니다. 예제의 품질 정답은 과거 회신 원장에만 있으며 현재 정답은 입력하지 않습니다.

## 전체 실험 재현

```powershell
.\.venv\Scripts\python.exe reproduce_submission.py --output verification_runs/research_replay --jobs 4
.\.venv\Scripts\python.exe verify_oct06.py
.\.venv\Scripts\python.exe analyze_oct06.py
.\.venv\Scripts\python.exe prepare_submission_demo.py
```

첫 명령은 새로운 폴더에 등록하고525개의 동일후보를 학습한 뒤 validation 선택을 봉인하고 재사용test 및 피드백 민감도를 평가합니다. 원래 selected_metrics.csv와210개 그룹의 지표를 대조합니다. 기존 원본·결과를 덮어쓰지 않습니다. 분석/데모 재생성 명령은 패키지의 해당 생성 결과를 갱신하므로 별도 복사본에서 실행하십시오.

원본3종은 data/raw, 고정 전처리·분할·계보는 data/processed에 있습니다. 변환 코드는 castguard/rebuild.py이며 기존모델코드와 분리한 새 연구는 castguard/oct06_research.py입니다. 주요 source는 현재 공정관측 기반이지만 품질 행의 원천 선정·정답 기반 완전중복 제거라는 역사적 모집단 한계는 유지됩니다.

## 해석

- 주 #42 품질 + 보조 #41 과거이력·상태를 비교했습니다. #40 온도제거는 별도 공정의 보조근거입니다.
- 현재 모델은S_FB/logistic/seed17. 같은 구간 재사용test 1,387건, 불량272, AUC0.7378/AP0.3845, 사후20% 순위검사117건 포착입니다.
- validation 임계값0.313415는test20% 검사량을 보장하지 않습니다. TP80/FP106/FN192/TN1,009이며 이 평가와사후top-k를 혼동하지 않습니다.
- 미래구간 일관성·#41 추가가치 채택실패를 유지합니다. 피드백효과는 #42 과거정답의효과이며 다종융합성과가 아닙니다. 모든 품질행은 과거평가에 노출됐고 신규독립검증이 아닙니다.
- 판독기는1,387행 중1,168행에서지원경고가 발생했습니다. 자동 위험표시·담당자검토요청은 구현했지만 실제라인 자동제어·생산중지·불량감소는 검증하지 않았습니다.
- 실제 수신시각·수집주기·단위·품질코드·검사비 확인이 현장 도입 조건입니다. 누락 품질은 정상으로채우지 않습니다.

## 구성과 예측

research_reader_predictions.csv: 연구판독기의고정test예측1,387행. reports/oct06_research/selected_predictions.parquet: 모든선택입력/fold/seed/role 예측. validation_candidates.csv는전체후보의개발지표, selection.json은test평가전선택기록입니다.

사전계획은docs/OCT06_RESEARCH_PROTOCOL.md, 수치·오류·공동지지·상호작용·불확실성·비용가정은reports/oct06_research에 있습니다. 105개의validation선택checkpoint와기존Gate1개를포함합니다. joblib은신뢰한이패키지의해시검증파일만읽고외부파일업로드를받지않습니다.

최종 보고서·발표PDF/PPTX는소스ZIP바깥에있습니다. build_oct06_submission.py는Windows폰트와reportlab/pypdf가있는문서환경에서보고서원고를재생성하는선택도구입니다. 모델재현에는필요없습니다. report_preview나모든과거자료/실험캐시는이패키지의필수구성이아닙니다.

설문 원본을 보고서에 첨부했습니다. 실제 서명·최종 포털 접수는 참가팀이 수행합니다. 소속 기업/학교·로고·로컬 사용자경로·Git 메타데이터는 포함하지 않습니다.
'''
    (STAGE/'README.md').write_text(readme,encoding='utf-8')
    items=[]
    for p in sorted(STAGE.rglob('*')):
        if p.is_file():items.append({'path':p.relative_to(STAGE).as_posix(),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    (STAGE/'PACKAGE_MANIFEST.json').write_text(json.dumps({'created_at':datetime.now(timezone.utc).isoformat(),'files':items,'scope':'curated reproducible research source; no submit receipt'},ensure_ascii=False,indent=2),encoding='utf-8')
    out=OUT/'CastGuard_source.zip'
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(STAGE.rglob('*')):
            if p.is_file():z.write(p,'CastGuard/'+p.relative_to(STAGE).as_posix())
    print('files',len(items)+1,'zip bytes',out.stat().st_size)


if __name__=='__main__':main()
