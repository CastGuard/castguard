"""Extend the verified source package without moving or removing working research paths."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import shutil
import zipfile

ROOT=Path(__file__).resolve().parent
BUILD=ROOT/'reports/oct08_submission'
STAGE=BUILD/'source_staging'
OUT=BUILD/'candidate'


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    if STAGE.exists():raise FileExistsError('Preserve prior package stage')
    STAGE.mkdir()
    with zipfile.ZipFile(BUILD/'before/submission/CastGuard_source.zip') as z:
        for name in z.namelist():
            if not (STAGE/name).resolve().is_relative_to(STAGE.resolve()):raise ValueError(name)
        z.extractall(STAGE)
    base=STAGE/'CastGuard'
    def copy(rel):
        p=ROOT/rel;target=base/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
    for rel in ['castguard/oct08_fusion.py','configs/oct08_fusion.json','docs/OCT08_FUSION_PROTOCOL.md',
                'tests/test_oct08_fusion.py','verify_oct08.py','verify_oct08_team.py','build_oct08_submission.py',
                'reports/oct08_submission/CastGuard_report.md','reports/oct08_submission/before/oct08_fusion_initial.py']:
        copy(rel)
    for folder in ['reports/oct08_fusion','reports/oct08_team_replay']:
        for p in (ROOT/folder).iterdir():
            if p.is_file():copy(p.relative_to(ROOT))
    for p in (ROOT/'reports/oct08_fusion/source').rglob('*'):
        if p.is_file():copy(p.relative_to(ROOT))
    for name in ['metrics.csv','registration.json','run_state.json','validation_seal.json','validation_metrics.csv']:
        copy('reports/oct08_fusion_reproduction/'+name)
    for p in (ROOT/'reports/oct08_team_reference/add_90402e0').rglob('*'):
        if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc':copy(p.relative_to(ROOT))
    (base/'predictions').mkdir(exist_ok=True)
    shutil.copy2(base/'research_reader_predictions.csv',base/'predictions/test_predictions.csv')
    shutil.copy2(OUT/'CastGuard_demo.html',base/'reports/oct08_submission/demo.html')
    (base/'README.md').write_text('''# CastGuard 제출 소스 · 10/8 통합본

팀명: RE제조부터시작하는이세계생활 / 팀장 정가현 / 팀원 신종훈

## 빠른 실행

Python 3.12 환경에서 다음 명령을 실행합니다. 모델 계산용 환경은 requirements-lock.txt에 잠겨 있습니다.

```powershell
python -m pip install -r requirements.txt
python -m pytest -q tests
python -m castguard.submission_reader --input examples/submission_reader/shots.json --output demo.json --html demo.html
```

출력 파일이 이미 있으면 다른 이름을 지정합니다. demo.html은 저장 모델의 실제 11개 입력 판독입니다. 현재 판독 모델은 기존 S_FB/logistic/seed17이며 새 전이 후보나 팀의 유형별/Gate 보조 모델로 교체하지 않았습니다.

## 네 가지 데이터 조합 재현

```powershell
python -m castguard.oct08_fusion --output verification_runs/fusion_replay --jobs 4 --reproduction
python verify_oct08_team.py --output verification_runs/team_replay
python verify_oct08.py
```

첫 명령은 #42, #42+#41, #42+#40, #42+#41+#40을 같은 고정 분할·3 seed·RF/로지스틱으로 비교합니다. 피드백 유무를 별도 층으로 두고 validation 지표를 봉인한 뒤 재사용 test를 계산합니다. 후보 240회와 source 모델 3회를 학습하며 계산 제한은 45분입니다. --reproduction은 대회일 이후에도 동일 설정을 재현하기 위한 모드이며 새로운 후보 선택이나 독립 검증을 뜻하지 않습니다.

두 번째 명령은 팀의 add 90402e0 코드와 데이터 사본에서 보존된 Gate·유형별 모델만 다시 계산합니다. 원래 22개 Gate 결과와 5개 유형 결과를 반올림 정밀도까지 재현했습니다. 20개 평가 행 지연의 정상 회신, 품질 행 순번 등의 가정이 현재 JH 판독기와 다르므로 보조 연구로 구분합니다. 별도 결과를 자동 설비 제어 또는 최종 판독 모델 교체로 해석하지 않습니다.

세 번째 명령은 패키지에 보존한 행별 예측·480개 지표·검증 재실행·기존 JH 78개 공통 평가 그룹·원본 해시를 대조합니다. 새로운 재현 경로의 결과를 대조하려면 metrics.csv를 scheme/fold/representation/model/seed/role로 일대일 연결해 지표를 비교하십시오. 초기 연구 코드의 사본은 reports/oct08_submission/before에 보존했고, 최종 코드에는 대회일 이후 재현 모드와 실행시간 제한만 추가했습니다.

## 주요 경로

| 경로 | 내용 |
| --- | --- |
| predictions/test_predictions.csv | 현재 판독 모델의 고정 test 1,387행 예측. research_reader_predictions.csv와 동일 바이트 |
| data/raw, data/processed | 원본 3종, 전처리, 고정 분할 및 데이터 계보 |
| reports/oct06_research | 기존 선정 모델·예측·성능과 조건 분석 |
| reports/oct08_fusion | 네 조합 지표·행별 예측·전이 source 모델·사전 등록·채택 판정·불확실성 |
| reports/oct08_team_replay | 팀 Gate·유형별 재현 결과와 분모 |
| reports/oct08_team_reference/add_90402e0 | 팀원이 작성한 코드·설정·데이터·원래 결과 사본 |
| reports/oct08_submission | 이번 보고서 원고와 정적 데모 |
| docs/OCT08_FUSION_PROTOCOL.md | 실행 전 고정한 가설·매핑·후보·성공/중단 조건 |

기존 전체 연구는 python reproduce_submission.py --output verification_runs/research_replay --jobs 4 로 재현합니다. 이 명령은 보존된 10/6 후보 525회를 다시 계산합니다. 문서 빌더는 별도 reportlab/pypdf 및 Windows 폰트를 요구하며 모델 재현에는 필요하지 않습니다.

## 결과와 적용 범위

같은 구간 재사용 test에서 현재 판독 모델의 AUC 0.7378/AP 0.3845, 사후 상위 277/1,387 검사로 불량 117/272(43.01%) 포착을 확인했습니다. validation 임계값 평가는 TP80/FP106/FN192/TN1009로 사후 top-k와 다릅니다. 1,168/1,387행의 지원 경고를 분모에서 빼지 않았습니다.

네 조합의 추가 입력은 사전 개선 기준에 미달했습니다. 이론적 변수 대응과 분위 정렬은 공정의 물리적 동등성이나 #42 실패 원인을 입증하지 않습니다. Gate의 정상 경보 부담·전체/관측 에피소드 분모, 유형별 AP·양성 수를 함께 보고합니다. 미래 구간·실제 수신 시각·현장 비용은 미검증입니다.

전체 소스의 PACKAGE_MANIFEST.json을 확인한 후 신뢰한 모델 파일만 읽으십시오. 실제 서명과 포털 접수는 참가팀이 수행합니다.
''',encoding='utf-8')
    # Retain the original checkpoint/input contracts; add new evidence without path migration.
    items=[{'path':p.relative_to(base).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(base.rglob('*')) if p.is_file() and p.name!='PACKAGE_MANIFEST.json']
    (base/'PACKAGE_MANIFEST.json').write_text(json.dumps({'created_at':datetime.now(timezone.utc).isoformat(),'files':items,
        'scope':'JH base plus registered four-combination study and reproduced team add evidence'},ensure_ascii=False,indent=2),encoding='utf-8')
    with zipfile.ZipFile(OUT/'CastGuard_source.zip','w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(base.rglob('*')):
            if p.is_file():z.write(p,'CastGuard/'+p.relative_to(base).as_posix())
    print('source files',len(items)+1,'bytes',(OUT/'CastGuard_source.zip').stat().st_size)


if __name__=='__main__':main()
