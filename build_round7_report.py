"""Build the source-bound scientific diagnostic, not a new presentation or model claim."""
from pathlib import Path
from datetime import datetime,timezone
import json
import pandas as pd
from castguard.data import digest
from verify_round7 import verify
ROOT=Path(__file__).resolve().parent

def table(frame,columns):
    def cell(v):
        if pd.isna(v):return '미관측'
        if isinstance(v,float):return f'{v:.3f}'
        return str(v)
    return '| '+' | '.join(columns)+' |\n|'+ '|'.join(['---']*len(columns))+'|\n'+''.join('| '+' | '.join(cell(row[c]) for c in columns)+' |\n' for _,row in frame.iterrows())

def build(root=ROOT):
    result=verify(root);out=root/'reports/oct03_round7'
    groups=pd.read_csv(out/'group_metrics.csv');eq=pd.read_csv(out/'fifo_history_equivalence.csv')
    uncertainty=pd.read_csv(out/'paired_uncertainty.csv');ties=pd.read_csv(out/'explanation/tie_summary.csv')
    waiting=pd.read_csv(out/'explanation/pooled_waiting.csv'); defects=pd.read_csv(out/'defect_metrics.csv')
    policy=groups.loc[groups.dimension.eq('all'),['policy','positive','inspected_mean','known_inspected_mean','hits_mean','capture','delta_hits_vs_FIFO']].copy()
    policy['capture_percent']=policy.capture*100
    run=groups.loc[groups.dimension.eq('run_id')&groups.policy.isin(['FIFO','Q','GQ']),['group','policy','positive','hits_mean','delta_hits_vs_FIFO']]
    d=defects.loc[defects.run_id.eq('all')&defects.policy.eq('Q')&defects.defect.isin(['Blow_Hole_1','Exfoliation_2','Short_Shot_1','Stain_1','Blow_Hole_2'])]
    txt='''# 회차7 진단: FIFO 우위는 무엇을 뜻하는가

판정: **모델의 현장 추가가치 주장에는 수정이 필요하다.** 회차6 숫자는 재현되지만, 과거 제품빈도는 이번 평가에서 FIFO와 같은 동점 정책이고 포착률 차이는 가동구간·대기시간·미관측 품질에 민감하다. 모델을 새로 학습하거나 정책을 채택하지 않았다. 기존 보고서는 보존하고 이 진단을 최신 해석 보충자료로 사용한다.

## 1. 비교 자체는 일치하지만 운영 가능성은 미확인

전체3395행, 품질정답2879행, 관측 양성505 Shot이다. 4개 바깥 개발구간과 같은20% 누적 검사 슬롯을 사용했다. FIFO/과거빈도/Q/GQ48개 구간·정책·시드 묶음을 별도 목록/min 구현으로 재생하여 검사 여부와 서비스 시점이 전부 일치했다. 보류 우선, 현재까지 도착한 행만 선택, 슬롯 이월 금지, 정답을 제외한 점수 입력을 확인했다. Q와 단순기준은675개, GQ는677개 검사다. GQ가 더 사용한2개 슬롯도 같은 규칙에서 생기며 예산 초과나 과거 슬롯 차입이 아니다.

'''+table(policy,['policy','inspected_mean','known_inspected_mean','hits_mean','capture_percent','delta_hits_vs_FIFO'])+'''
표의 hits는 관측된 품질양성만 센다. 미관측 품질을 실제 정상으로 간주하지 않는다. 5개 모델 seed는 같은 평가자료를 공유하며 독립 표본이 아니다. 모델·최근빈도의 fit은 평가행보다 앞선 파일 순서이고 평가라벨 값은 점수·queue에 없다. 하지만 **생산·센서 수신·검사 완료의 실제 타임스탬프가 없으므로 현장 누수 없음이나 즉시 입력 가능성을 인증하지 못한다.** q42 존재행 mask와 `shot_position`(q42행 누적순번)은 현장 관측 가능성이 미확인이다. 파일 순서의 run은 실제 생산시각이 아니다. 학습 라벨도 사용 시점에 검사완료됐는지 확인할 자료가 없다.[S1,S2,S7]

## 2. FIFO와 과거 제품빈도는 별개의 성공 근거가 아니다

각 평가 run에는 제품 코드가 하나뿐이다. 최근100개 fit 품질행으로 계산한 빈도는 각각0.25,0.25,0.03,0.00으로 구간 내 상수다. 제품2인600+725행은 최근 fit에 해당 제품이 없어 전체 최근빈도로 fallback했다. 검사 행 차이0, 서비스 시점 차이0이다. 이 일치는 통계적 우연이나 제품정보의 유효성 증거가 아니라 **상수 점수와 FIFO 동점 처리의 결정적 결과**다.[S3]

'''+table(eq,['run_id','evaluation_products','recent_fit_products','constant_score','fallback_rows','inspection_disagreements','service_time_disagreements'])+'''
같은 상수 점수에서 동점만 LIFO로 바꾸면 포착률19.802%, 난수 동점100회 평균19.756%로 바뀐다(FIFO22.376%). 난수 동점의2.5~97.5분위는16.832~22.574%이다. 이는 이미 본 자료의 민감도이지 LIFO/난수 정책을 선정하는 실험이 아니다. 고정 난수 tie는 회차6의 무작위 우선순위와 같은 정책군이며 seed집합이 달라 평균이 약간 다르다. 둘을 독립적으로 우수한 기준으로 세지 않는다.[S4]

## 3. Q의 열세는 run1의 초반 불량 누락이 지배한다

'''+table(run,['group','policy','positive','hits_mean','delta_hits_vs_FIFO'])+'''
Q는 FIFO 대비 run1에서14건 덜 포착하고 나머지 구간에서는 합계6.4건 더 포착해 총−7.6건(−1.505%p)이다. run1을 제외하면+1.844%p로 부호가 바뀐다. 제품1의 차이는−14건, 제품2는+6.4건이지만 제품과 run이 겹치므로 제품 자체가 원인이라고 단정하지 않는다. 두 제품2 평가구간의 모델 fit에도 제품2가 없었다(1325개 미경험 제품행). 이 전달 조건은 별도 검증이 필요하다.[S1,S5]

run1의 첫 도착순4분위는324개 품질행 중68양성(20.988%), 마지막4분위는294개 중24양성(8.163%)이다. FIFO는 이 run의176개 품질검사를 첫4분위에 모두 써46개 양성을 잡았다. Q는 첫4분위127개 검사에서27개를 잡고, 두번째/세번째4분위에서4/1개를 더 잡았다. 첫4분위 손실−19를 후반+5로 만회하지 못했다. 행을 직접 짝지으면 FIFO만 잡은 양성30개, Q만 잡은 양성16개, 둘 다 잡은 양성16개다.

Q 점수도 run1에서 시간순으로 감소한다(Spearman−0.807). 따라서 “모델이 단순히 후반을 더 위험하게 보았다”는 설명은 맞지 않는다. 전체 run1 AUC0.595/AP0.187이 양성률0.137보다 높아도, 지연검사 queue의 유한 종료시점에서 FIFO가 고르는 초기 집합보다 유용하지 않았다. 이는 전역 순위 성능과 제한된 서비스 기회의 목적이 다를 수 있음을 보여준다. 어떤 공정 변수가 물리적 원인인지는 이 계산으로 알 수 없다.[S5]

불량별로 전체 Q−FIFO 손실은 Blow_Hole_1−18, Exfoliation_2−15, Short_Shot_1−9이고 Stain_1+18 등 이득도 있다. run1의 주 손실은 Exfoliation_2−15와 Short_Shot_1−7이다. 26개 불량열은 한 Shot에 중복되므로 이 차이를 더해 전체−7.6건을 만들면 안 된다.[S6]

'''+table(d,['defect','positive_shots','hits_mean','delta_hits_vs_FIFO'])+'''
## 4. 가용성과 대기시간은 핵심 운영 제약이다

현재 품질점수 존재mask는 품질정답 존재와 정확히 일치한다. 미관측516행은 공정결손 hold409행과 공정완전/품질점수없음107행이다. 모든 정책은 같은 hold409행 중168행을 검사하고241행을 남긴다. Q/FIFO는 품질관측행507개를 검사한다. GQ는486.2개로20.8개 줄이고, 점수가 없는 공정완전행을22.8개 더 검사한다(총2개 검사 증가). 이516행의 품질이 없어 전체 생산 흐름의 진짜 불량 포착률은 미측정이다.

GQ−Q의 관측양성−3.2건은 같은 서비스 슬롯에서 품질→gate 교체로−1.6건, 이후 품질 대기열 순서변경으로−1.6건이다. 추가2슬롯은 gate 검사였고 관측된 품질양성은 없었다. 이 값은 파일에서 확인된 산술 분해이며 예열구간의 실제 품질편익이0이라는 뜻이 아니다. Gate의 목적을 검증하려면 예열/품질 미관측 구간의 품질과 조치 결과가 필요하다.[S1,S5]

FIFO가 검사한 품질행507개와 포착113개는 모두 각 run의 첫4분위 도착행이다. 전체기록 기준 품질검사 평균 대기는 FIFO310.308, Q142.253, GQ144.709다. FIFO의 포착률은 더 오래 보관한 초기 생산물에 집중한 결과와 함께 평가해야 한다. 최대 보관기간·검사 완료시간·최종 queue 처리/폐기 규칙을 모델링하지 않았으므로 같은 검사 수가 같은 현장 가치라는 보장은 없다. 기록 수를 분·시간으로 바꾸지 않는다.

참고로 품질파일 존재mask를 없애고 공정완전행도 FIFO 대기열에 넣으면677검사, 관측 품질487개, 미관측190개, 알려진 양성112개다. 이는 다른 가용성 가정의 민감도일 뿐, 전체 품질 포착률을 계산하거나 새 정책으로 채택할 수 있는 실험이 아니다.[S1,S4,S5]

## 5. 시간 의존을 유지해도 우열을 확정할 근거는 부족하다

양성·두 정책 행동을 같은 행으로 묶고 모델5 seed의 평균 행동을 사용했다. run 전체를 보존한4^4=256개 cluster 재표본과 각 run 내부 연속25/50/100기록 moving-block4000회를 계산했다. 아래는2.5~97.5분위 범위다.

'''+table(uncertainty,['policy','method','block_records','point_pp','lower_pp','upper_pp'])+'''
모두0을 포함한다. 단4개 run이며 run 간 학습자료도 겹치고 제품/불량률 변화가 크다. 전체run bootstrap의 교환가능성과 moving-block의 안정적인 시계열 가정을 강하게 믿을 수 없다. 일부 실제 대기 길이는100기록 블록보다 길다. 따라서 **정식95% 일반화 신뢰구간·유의성 검정으로 표시하지 않는다.** moving-block은 고정된 행동의 조건부 재표본이며, 큐를 새로 돌리거나 모델을 재학습한 분포가 아니다. 시간 블록 원리는 [Künsch(1989)의 원 논문](https://projecteuclid.org/journals/annals-of-statistics/volume-17/issue-3/The-Jackknife-and-the-Bootstrap-for-General-Stationary-Observations/10.1214/aos/1176347265.short)을 참고했으며, 여기의 가정 제한은 현재 자료에서 확인한 판단이다.[S8]

## 6. 정직하게 남아 있는 평가와 다음 결정

품질4617행 중 기존 평가 적격4613행은 모두 과거 test 예측에 들어 있다. 나머지4행은 run5의 작은 제외구간으로, 원본 감사에서 이미 라벨이 확인됐다. 독립 holdout으로 재활용할 수 없다. 현재 저장소에서 적법하게 미노출된 품질 평가자료를 찾지 못했다.[S7]

이번에 새로운 모델/임계값/정책을 고르지 않는다. 자료를 다시 나누거나 FIFO가 이긴 뒤 FIFO를 운영정책으로 승격하는 것은 이 약점을 해결하지 않는다. 허용 결론은 “동일한 저장자료 시뮬레이션에서 Q/GQ의 FIFO 대비 추가가치를 확인하지 못했고, 제품/구간·관측선택·지연 제약을 해결한 미래 평가가 필요하다”이다. 검사 프로세스 자체의 실패가 확인된 것은 아니며 현장 경제효과는 여전히 미측정이다.

최소 새 데이터와 평가계약은 [NEW_DATA_REQUIREMENTS.md](NEW_DATA_REQUIREMENTS.md)에 고정했다. 지원자료가 없으면 새 탐색을 늘리지 않고 관측된 한계와 재현 가능한 검증 사례로 발표 범위를 제한한다.

## 재현과 출처

기존 Python 환경에서 `python -B verify_round7.py`로 입력·출력 해시와 독립 산술을 확인한다. 진단 재계산은 `python -B diagnose_round7.py --output reports/reproduction/round7_new`처럼 새 경로를 사용한다. `python -B run_review_tests.py`로 관련 테스트를 확인한다. 새환경 설치·모델 재학습은 이번 범위가 아니다.

- S1: `paired_rows.parquet`, `group_metrics.csv` — 3395개 행의 비교·분모·가용성·시간 분해.
- S2: `replay_audit.csv`, `../oct03_queue/selection.json`, `../../data/processed/feature_contract.json`, `../../castguard/rebuild.py` — 입력·분할·독립 서비스 재생.
- S3: `fifo_history_equivalence.csv` — 상수 점수·fallback·행별 완전일치.
- S4: `tie_sensitivity.csv`, `explanation/tie_summary.csv`, `full_availability_fifo.csv` — 동점·가용성 민감도.
- S5: `score_chronology.csv`, `explanation/score_rank_by_run.csv`, `explanation/discordant_positive_pairs.csv`, `explanation/fit_product_exposure.csv`, `explanation/gq_q_slot_summary.csv`, `explanation/pooled_waiting.csv`.
- S6: `defect_metrics.csv` — 중복 불량 유형의 분모와 포착.
- S7: `evaluation_exposure.json`, `../oct02/predictions.parquet` — 기존 test 노출과 현장 타이밍 미확인.
- S8: `paired_uncertainty.csv`, `leave_one_run_out.csv` — 짝지은 재표본과 구간 민감도.

모든 계산 소스·설정·입력 SHA-256은 `registration.json`, 계산 결과 해시는 `receipt.json`과 `explanation/receipt.json`에 있다. 외부제출·공개·원격푸시·구매·Library/HWPX 재시도는 하지 않았다.
'''
    (out/'DIAGNOSTIC.md').write_text(txt,encoding='utf-8')
    values={'verified':result,'report_sha256':digest(out/'DIAGNOSTIC.md'),
      'created_at':datetime.now(timezone.utc).isoformat(),'scope':'diagnostic amendment to preserved round6 report',
      'model_or_policy_promoted':False,'claim_status':'Needs revision for operational superiority claims'}
    (out/'report_receipt.json').write_text(json.dumps(values,indent=2),encoding='utf-8')
    print(json.dumps(values))

if __name__=='__main__':build()
