"""Versioned review report incorporating round7 diagnosis and a non-performance contract."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
import json,re
import pandas as pd
from castguard.data import digest
from verify_round7 import verify
ROOT=Path(__file__).resolve().parent

def build(root=ROOT):
    verify(root)
    source=root/'reports/submission_round6';out=root/'reports/submission_round8';out.mkdir(parents=True,exist_ok=True)
    old=(source/'CastGuard_form_draft.md').read_text(encoding='utf-8')
    old_index=json.loads((source/'report_evidence.json').read_text(encoding='utf-8'))
    assert digest(source/'CastGuard_form_draft.md')==old_index['report_sha256']
    metrics=dict(old_index['metrics']);g=pd.read_csv(root/'reports/oct03_round7/group_metrics.csv')
    w=pd.read_csv(root/'reports/oct03_round7/explanation/pooled_waiting.csv')
    u=pd.read_csv(root/'reports/oct03_round7/paired_uncertainty.csv')
    def fact(name,value,path,selector,unit,decimals=3):
        display=str(int(value)) if decimals==0 else f'{value:.{decimals}f}'
        metrics[name]={'value':float(value),'display':display,'source':path,'selector':selector,'unit':unit,'sha256':digest(root/path)}
        return display
    main=g.loc[g.dimension.eq('all')].set_index('policy');perrun=g.loc[g.dimension.eq('run_id')].set_index(['group','policy'])
    qdelta=fact('R7_Q_DELTA_HITS',main.loc['Q','delta_hits_vs_FIFO'],'reports/oct03_round7/group_metrics.csv','dimension=all,policy=Q,delta_hits_vs_FIFO','mean observed positive shots',1)
    r1=fact('R7_RUN1_DELTA',perrun.loc[('1','Q'),'delta_hits_vs_FIFO'],'reports/oct03_round7/group_metrics.csv','dimension=run_id,group=1,policy=Q,delta_hits_vs_FIFO','mean observed positive shots',1)
    remaining=fact('R7_OTHER_DELTA',main.loc['Q','delta_hits_vs_FIFO']-perrun.loc[('1','Q'),'delta_hits_vs_FIFO'],'reports/oct03_round7/group_metrics.csv','Q all delta minus run1 delta','mean observed positive shots',1)
    wait={p:fact('R7_WAIT_'+p,float(w.loc[w.policy.eq(p)&w.population.eq('quality_known'),'mean_wait_records'].iloc[0]),'reports/oct03_round7/explanation/pooled_waiting.csv',f'policy={p},population=quality_known,mean_wait_records','records') for p in ['FIFO','Q']}
    qci=u.loc[u.policy.eq('Q')&u.method.eq('whole_run_cluster_exact_enumeration')].iloc[0]
    low=fact('R7_Q_CLUSTER_LOW',qci.lower_pp,'reports/oct03_round7/paired_uncertainty.csv','Q whole_run_cluster_exact_enumeration lower_pp','percentage points')
    high=fact('R7_Q_CLUSTER_HIGH',qci.upper_pp,'reports/oct03_round7/paired_uncertainty.csv','Q whole_run_cluster_exact_enumeration upper_pp','percentage points')
    exposure=json.loads((root/'reports/oct03_round7/evaluation_exposure.json').read_text())
    exposed=fact('R7_EXPOSED_TEST',exposure['prior_test_unique_rows'],'reports/oct03_round7/evaluation_exposure.json','prior_test_unique_rows','quality rows',0)
    summary='주조 품질과 설비 기록을 연결해 같은 검사 용량의 배분을 비교했다. 이미 본 개발 흐름에서 FIFO 22.376%, Q 20.871%, GQ 20.238%였으나, 과거빈도는 상수 점수로 FIFO와 동일했고 구간·대기시간에 따라 결론이 달라졌다. 어느 정책의 현장 우위도 입증하지 못했다. 미노출 평가자료가 없어 새 정책을 선정하지 않았으며, 실제 입력·검사 시점과 독립 품질표본을 위한 오프라인 검증 계약을 마련했다. 합성 기능시험은 성능 근거와 분리했다.'
    old_summary=old.split('## 내용요약\n\n',1)[1].split('\n\n상기 ',1)[0]
    text=old.replace(old_summary,summary,1)
    assert '| 과거 제품별 빈도 |' in text
    text=text.replace('| 과거 제품별 빈도 |','| 과거 제품별 빈도(FIFO와 동일 행동) |')
    # Actual earlier wording is preserved except for the now-verified interpretation.
    paragraph=next(p for p in text.split('\n\n') if p.startswith('FIFO와 과거 빈도는 113/505개'))
    replacement='FIFO와 과거 빈도는 모두 113/505개(22.376%)였지만 독립적인 두 기준의 성공이 아니다. 평가 run마다 제품이 하나라 최근빈도 점수는 구간 안에서 상수였고, 동점 FIFO로 검사 행·처리 시점까지 완전히 같았다. 제품2의1325행은 최근 fit에 제품이 없어 전체빈도로 fallback했다. 두 이름의 결과를 별개의 성능 증거로 세지 않는다. 이 자료에서 Q20.871%와 GQ20.238%보다 높았다는 사실은 FIFO의 현장 우위나 미래 일반화를 입증하지 않는다.[J01,D07]'
    text=text.replace(paragraph,replacement,1)
    oldplan='먼저 현장의 기존 검사 방식을 확인하고 FIFO·과거빈도 기준과 제안 정책을 같은 도착 흐름에서 기록만 하는 shadow 평가로 비교한다.'
    text=text.replace(oldplan,'먼저 현장 검사·대기 규칙과 입력 도착시각을 확인하고, FIFO(현재 과거빈도와 동일 행동)와 동결한 후보를 미래 생산 흐름에서 기록만 하는 shadow 평가로 비교한다.')
    diagnostic=f'''### 단순 기준 차이의 원인과 불확실성

Q−FIFO는 전체 {qdelta}건이며 run1 {r1}건과 나머지 +{remaining}건의 합이다. run1을 제외하면 차이의 부호가 바뀐다. run1에서 FIFO만 잡은 양성30개, Q만 잡은16개였고 Exfoliation_2와 Short_Shot_1 누락이 주요 유형이다. 같은 Shot의 불량이 중복될 수 있으므로 유형별 차이를 합산하지 않는다. 제품은 run과 겹쳐 제품 자체의 인과효과로 해석하지 않는다.[D07]

FIFO가 검사한 품질행507개는 모두 각 run의 첫 도착4분위에 속했다. 품질검사 평균 대기는 FIFO {wait['FIFO']}기록, Q {wait['Q']}기록이다. 기록 수는 실제 시간 단위가 아니다. 실제 보관 한도와 검사 완료시각을 모르면 포착률만으로 운영 우위를 정할 수 없다. 전체516행의 품질이 미관측이고, GQ가 Q보다 품질 미관측행22.8개를 더 검사한 효과도 실제 품질 편익으로 계산할 수 없다.[D07]

4개 run을 유지한256개 재표본에서 Q−FIFO의2.5~97.5분위는 {low}~+{high}%p이며, 연속25/50/100기록 블록 재표본도0을 포함했다. 소수 run·겹치는 학습자료·비정상적 시계열과 이미 본 자료라는 한계가 있으므로 정식 일반화 신뢰구간이나 유의성으로 표현하지 않는다. 새 후보나 임계값을 이 결과로 고르지 않았다.[D07]

적격 품질 {exposed}행 모두 과거 test에 노출됐다. 나머지4개 제외행도 이미 감사에서 라벨이 확인돼 정당한 미노출 holdout이 없다. 새 생산과 독립 품질관측 없이는 추가 성능 선택을 진행하지 않는다. 실제 입력 수신시각과 학습 라벨 수신시각도 확인되지 않아 파일 순서의 인과성 검사를 현장 누수 없음의 인증으로 확대하지 않는다.[D07]

'''
    text=text.replace('## 제4장.',diagnostic+'## 제4장.',1)
    interface='''### 새 자료의 평가 계약과 검증 인터페이스

미래 평가용 JSON 계약과 빈 CSV8개를 만들었다. 전체 생산행·입력 측정/수신·정책 점수·독립 감사 선택·검사 시작/완료/라벨 수신·공통 검사 슬롯·정책별 배정·학습 라벨 사용기록을 분리한다. 기본 계약은 미완료 상태이며 실제 시각이나 현장 수치를 생성해 채우지 않았다.[F08]

모든 정책에 같은 관측시점·전체 생산행·검사 자원·대기 한도·만료 조건을 강제한다. 입력이 결정시점에 없으면 공통 hold FIFO이고, 제한된 대기열은 가득 차면 새 행을 거절한다. 검사 시작뿐 아니라 완료가 만료와 평가 종료 이내인지 확인한다. 미래 입력/정답 사용, 품질 관측행만 남긴 비교, 정책별 다른 정보시점·예산, 중복 자원 슬롯을 차단한다.[F08]

독립 감사는 전수 또는 미리 잠근 seed와 확률의 hash-Bernoulli 표본이다. 독립 감사의 자원은 정책 검사와 별개라는 좁은 조건만 지원한다. 학습 라벨은 실제 수신 후, 정책 동결 전에만 사용한다. 원천 해시와 원본 event_id가 과거자료와 같으면 새 평가로 거부한다. 이름을 바꾼 자료의 노출 이력이나 진짜 시각까지 파일만으로 보증하지는 못한다.[F08]

합성 fixture는 기능 시험에만 쓰고 성능표에 포함하지 않는다. 구조 통과도 사람의 원천 확인 전 단계이며, 성능 근거 생성·현장 인증을 뜻하지 않는다. 가변 검사시간·연결된 다중queue·감사 자원공유는 별도 계약이 필요하다. 현재는 새 데이터와 사용자 운영조건이 필요한 지점에서 성능 작업을 중단했다.[F08]

'''
    text=text.replace('### 제출 전 남은 필수 항목',interface+'### 제출 전 남은 필수 항목',1)
    text=text.replace('python verify_judge_baselines.py','python verify_judge_baselines.py\npython verify_round7.py',1)
    assert '## 부록 근거 목록과 검토 질문' in text
    text=text.replace('## 부록 근거 목록과 검토 질문','## 부록 근거 목록과 검토 질문\n\nD07 `reports/oct03_round7/DIAGNOSTIC.md`, 해당 폴더의 CSV/JSON과 `explanation/`: 동점·구간·대기·관측 선택·과거 평가 노출.\n\nF08 `future_evaluation.py`, `docs/FUTURE_EVALUATION_CONTRACT.md`, `docs/DATA_REQUEST_ROUND8.md`, `templates/future_evaluation/`, `tests/test_future_evaluation.py`: 미래 계약과 합성 기능시험. 성능 근거 아님.',1)
    text=text.replace('`reports/submission_draft/evidence_index.json`','`reports/submission_round8/report_evidence.json`').replace('`PACKAGE_README.md`','`ROUND8_README.md`')
    text=text.replace('검토용 편집초안:', '회차8 최신 검토용 편집초안:',1)
    (out/'CastGuard_current_review.md').write_text(text,encoding='utf-8')
    extra=['future_evaluation.py','docs/FUTURE_EVALUATION_CONTRACT.md','docs/DATA_REQUEST_ROUND8.md','tests/test_future_evaluation.py',
      'reports/oct03_round7/DIAGNOSTIC.md','reports/oct03_round7/receipt.json','reports/oct03_round7/explanation/receipt.json']
    index={'report_sha256':digest(out/'CastGuard_current_review.md'),'previous_report_sha256':digest(source/'CastGuard_form_draft.md'),
      'metrics':metrics,'new_contract_not_performance':True,'synthetic_fixtures_in_performance_tables':False,
      'new_policy_selection':False,'native_hwpx_created':False,'source_hashes':{p:digest(root/p) for p in extra},
      'changes':['FIFO/history are identical actions, not distinct successful baselines','no model or FIFO field superiority established',
       'round7 paired diagnosis and prior test exposure','future evaluation contract and functional-only synthetic tests']}
    (out/'report_evidence.json').write_text(json.dumps(index,ensure_ascii=False,indent=2),encoding='utf-8')
    renderer=(root/'render_submission_round6.py').read_text(encoding='utf-8').replace("OUT=ROOT/'reports/submission_round6'","OUT=ROOT/'reports/submission_round8'")
    renderer=renderer.replace('CastGuard_form_draft','CastGuard_current_review').replace('공식 보고서 양식 대응 검토초안','회차8 최신 공식 양식 대응 검토초안')
    (root/'render_submission_round8.py').write_text(renderer,encoding='utf-8')
    print(json.dumps({'metrics_bound':len(metrics),'new_diagnostic_facts':len(metrics)-len(old_index['metrics']),'report_bytes':(out/'CastGuard_current_review.md').stat().st_size}))

if __name__=='__main__':build()
