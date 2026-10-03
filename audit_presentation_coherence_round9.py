"""Cross-artifact denominator/terminology audit; no fitting or candidate selection."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
import csv,json
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'reports/presentation_round9'
def rows(name):return list(csv.DictReader((ROOT/name).open(encoding='utf-8-sig',newline='')))
paths=['reports/oct03_queue/nested_assignments.csv','reports/oct03_round7/group_metrics.csv',
 'reports/oct03_pilot_r2/q1_comparison.csv','reports/submission_round8/CastGuard_current_review.md',
 'reports/presentation_round9/slide_evidence.json','docs/PREPROCESSING.md']
assign,groups,q1=[rows(name) for name in paths[:3]]
mapping=[]
for fold in ['2','3','4','6']:
    evalrows=[r for r in assign if r['fold']==fold and r['nested_role']=='evaluation']
    runids={r['run_id'] for r in evalrows};assert len(runids)==1
    run=next(iter(runids));sizes={dataset:len([r for r in evalrows if r['dataset']==dataset]) for dataset in ['m41','q42']}
    g=next(r for r in groups if r['dimension']=='run_id' and r['group']==run and r['policy']=='FIFO')
    assert sizes['m41']==int(g['rows']) and sizes['q42']==int(g['quality_known'])
    ss=[r for r in q1 if r['scheme']=='forward_run' and r['fold']==fold and float(r['budget'])==.2]
    positives={int(float(r['positive'])) for r in ss};assert len(positives)<=1
    mapping.append({'fold':fold,'run_id':run,'production':sizes['m41'],'quality_known':sizes['q42'],
      'any_defect_positive':int(g['positive']),'q1_short_shot_positive':next(iter(positives)) if positives else None})
assert sum(r['production'] for r in mapping)==3395 and sum(r['quality_known'] for r in mapping)==2879 and sum(r['any_defect_positive'] for r in mapping)==505
table='\n'.join(f'| {r["run_id"]} | {r["fold"]} | {r["production"]} | {r["quality_known"]} | {r["any_defect_positive"]} | {r["q1_short_shot_positive"] if r["q1_short_shot_positive"] is not None else "해당 미래 Q1 비교 없음"} |' for r in mapping)
doc='''# 보고서·발표 일치 검토와 발표자 용어표

회차9 최종 반영 후 이어서 확인했다. 모델 성능 실험이나 후보 재선정은 하지 않았다. 회차8 보고서와 회차9 발표의 핵심 정책 수치·실패 판정은 일치한다. 다음 항목은 심사 답변에서 같은 단어를 다른 뜻으로 쓰기 쉬워 별도로 고정했다.

## 혼동을 막을 다섯 가지 구분

| 표현 | 정확한 의미 | 쓰면 안 되는 해석 |
|---|---|---|
| 정상FPR의 정상 | 설비 상태 Machine_Status=0. queue 분모3,191행 | 품질 양품이라는 뜻. 해당 행에 품질 불량이 함께 존재할 수 있음 |
| Q와 Q1 | Q는 순차 queue의 전체 불량 위험도 정책. Q1은 별도 Short_Shot 전문화 실험 | 같은 모델·같은 라벨·같은 평가라고 혼합 |
| 20% 검사 | queue는 누적 자원 상한. Q1은 각 구간 전체 순위에서 floor(n×.2) 검사 | 동일한 검사행·처리순서를 갖는 한 실험 |
| A와 B | A는 #42 공정·센서·제품·관측순번22입력. B는 #41의 과거 이력4개 추가 | A가 공정14입력 A0와 같거나 #40 결합 모델이라는 뜻 |
| 102와109시험 |102는 보존된 회차8 시점.109는7개 회귀시험 추가 후 회차9 | 성능 표본이 늘었거나 모델 점수가 상승했다는 뜻 |

보고서의 기업문제 문장에 있는 “품질 가능성이 높은 Shot”은 방향이 모호하다. 발표/최종 양식 편집에는 **“불량 위험도가 높은 Shot에 제한된 검사 용량을 우선 배정한다”**를 사용한다. 보존한 회차8 PDF를 소급 수정하지 않으며, 이 문구 교정은 위험도의 방향을 명확하게 할 뿐 결과·정책을 바꾸지 않는다.

## 발표 run과 원래 fold는 이름이 다르다

`nested_assignments.csv`의 실제 evaluation행과 회차7의 FIFO 그룹표를 대조했다. run은 파일 순서에서 파생된 가동구간이며 실제 날짜를 복원한 번호가 아니다. Q1 전문화 양성은 전체 불량의 일부이므로 두 분모를 혼동하지 않는다.

| 발표 run | 원래 fold | 생산 기록 | 품질 관측 | 전체 불량 양성 | Q1 Short_Shot 양성 |
|---|---:|---:|---:|---:|---:|
TABLE

합계는 생산3,395·품질 관측2,879·전체 불량 양성505다. 차이516행의 품질은 미관측이며 정상/불량0으로 바꾸지 않는다. run1의 전체 양성158과 Q1 fold2의 Short_Shot 양성64는 서로 다른 라벨의 분모로 양립한다. Q1 표의10/20/30% 성과를 queue 정책의 같은 용량 결과로 붙여 해석하지 않는다.

## 비교 수치의 최종 읽기

- 발표5장/보고서3장: FIFO22.376%, Q20.871%, GQ20.238%. 관측 양성505개 분모, 과거4구간. 제품빈도는 FIFO와 동일 행동.
- 발표6장: within_run A→B AP .2614→.2668과, 순차 queue Q→GQ 포착률20.871→20.238%는 다른 평가다. AP 증가와 포착률 차이를 합산하지 않는다.
- 발표7장: 정상 자동 FPR1.091→.094%의 감소만으로 성공을 선언하지 않는다. 정상 경보∪보류10.868→34.942%, 미처리241→988과 함께 읽는다.
- 발표9장: 조건부 run 재표본 범위는 일반화CI가 아니다.310대142는 검사된 품질행의 기록 수 대기이며 실제 분이 아니다.
- 발표10~12장: 기능 계약과 미래 계획은 실제 자료·현장 성능 검증 결과가 아니다. 미동결 계획을 사전등록 완료로 부르지 않는다.

## 최종 편집 시 적용

이미 검수한 발표PPTX/PDF와 이전 보고서를 보존했다. 실제 발표시간과 팀의 리허설이 정해지면 이 용어표를 기준으로 원고를 다듬는다. 공식 발표시간·파일 규격·실제 기업 효과의 공백은 이 일치 검토로 해소되지 않는다. 다음 보고서 편집본에는 위 방향 문구 교정을 반영하고 새 버전으로 저장한다.
'''.replace('TABLE',table)
(OUT/'COHERENCE_REVIEW.md').write_text(doc,encoding='utf-8')
receipt={'checked_at':datetime.now(timezone.utc).isoformat(),'run_fold_map':mapping,
 'production_rows':3395,'quality_observed_rows':2879,'known_any_defect_positives':505,'unobserved_quality':516,
 'main_cross_artifact_verification':'checks/artifact_verification.json',
 'editorial_clarification':'quality possibility -> defect risk; no historical PDF overwritten',
 'new_training':False,'new_performance_evidence':False,
 'source_hashes':{name:sha256((ROOT/name).read_bytes()).hexdigest() for name in paths}}
(OUT/'checks/coherence_review.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'run_fold_pairs':len(mapping),'production_rows':3395,'quality_observed':2879,'positives':505},ensure_ascii=False))
