"""Build six-chapter submission report from sealed results, preserving earlier drafts."""
from pathlib import Path
import hashlib
import html
import json
import shutil
import re
from datetime import datetime, timezone, timedelta
import pandas as pd
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, PageBreak, Image, KeepTogether
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from pypdf import PdfReader, PdfWriter

ROOT=Path(__file__).resolve().parent
E=ROOT/'reports/oct06_research'
BUILD=ROOT/'reports/oct06_submission'
OUT=ROOT/'submission'
TEAM='RE제조부터시작하는이세계생활'


def markdown_table(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+
                     ['| '+' | '.join(str(x) for x in row)+' |' for row in rows])


def content():
    s=pd.read_csv(E/'summary.csv',dtype={'fold':str});within=s[(s.scheme=='within_run')&(s.role=='test')].set_index('representation')
    val=s[(s.scheme=='within_run')&(s.role=='validation')].set_index('representation')
    stress=pd.read_csv(E/'feedback_sensitivity.csv');stress=stress[(stress.scheme=='within_run')&(stress.role=='test')&(stress.representation=='S_FB')].groupby('scenario')[['ap','auc','capture20']].mean()
    support=pd.read_csv(E/'reader_support_audit.csv');manual=int(support.manual_review.sum())
    inter=pd.read_csv(E/'pair_interactions.csv');unc=json.loads((E/'reader_uncertainty.json').read_text())
    quality=json.loads((E/'demo_output.json').read_text(encoding='utf-8'))['records'][0]['quality']
    top=sorted(quality['explanation']['contributions'],key=lambda x:-abs(x['contribution']))[:5]
    metrics_table=markdown_table(['입력 / 선택모델','validation AP','재사용 test AP','AUC','20% 포착률'],[
        [f'{r} / {within.loc[r,"model"]}',f'{val.loc[r,"ap"]:.4f}',f'{within.loc[r,"ap"]:.4f}',f'{within.loc[r,"auc"]:.4f}',f'{within.loc[r,"capture20"]*100:.2f}%']
        for r in ['P','H','S','SH','FB','S_FB','SH_FB']])
    forward=s[(s.scheme=='forward_run')&(s.role=='test')&(s.representation=='S_FB')]
    forward_table=markdown_table(['평가 run','Shot / 불량','AP','AUC','20% 포착률'],[[x.fold,f'{x.n} / {x.positive}',f'{x.ap:.4f}',f'{x.auc:.4f}',f'{x.capture20*100:.2f}%'] for x in forward.itertuples()])
    stress_table=markdown_table(['회신 조건(모델 동결)','AP','AUC','20% 포착률'],[
        [label,f'{stress.loc[key,"ap"]:.4f}',f'{stress.loc[key,"auc"]:.4f}',f'{stress.loc[key,"capture20"]*100:.2f}%']
        for key,label in [('delay5','5 event 지연'),('delay50','50 event 지연'),('delay100','100 event 지연'),('coverage0.5','관측률50%'),('coverage0.2','관측률20%'),('no_current_partition_returns','test 구간 정답 회신 없음')]])
    conditions=pd.read_csv(E/'condition_errors.csv');g=conditions[(conditions.scheme=='within_run')&(conditions.representation=='S_FB')&(conditions.dimension=='run_id')].groupby('value').agg(n=('n','first'),positive=('positive','first'),ap=('ap','mean'),auc=('auc','mean'),fp=('fp','mean'),fn=('fn','mean'))
    error_table=markdown_table(['run','Shot / 불량','AP / AUC','오탐 FP','미탐 FN'],[[i,f'{int(x.n)} / {int(x.positive)}',f'{x.ap:.3f} / {x.auc:.3f}',f'{x.fp:.0f}',f'{x.fn:.0f}'] for i,x in g.iterrows()])
    examples=pd.read_csv(E/'diagnostic_examples.csv')
    example_table=markdown_table(['사례','Shot 식별자','위험 점수','정답'],[[x.error_type,x.row_id,f'{x.probability:.4f}',int(x.y_defect)] for x in examples.itertuples()])
    cost=pd.read_csv(E/'cost_scenarios.csv').pivot(index='miss_cost_per_inspection_cost',columns='policy',values='normalized_loss')
    cost_table=markdown_table(['누락비/검사비 비율','S 손실','S_FB 손실','S 대비 감소율'],[[k,f'{v.S:.0f}',f'{v.reader:.0f}',f'{(v.S-v.reader)/v.S*100:.2f}%'] for k,v in cost.iterrows()])
    text=f'''# CastGuard: 근거를 설명하는 품질검사 의사결정 지원

팀명: {TEAM}
팀장: 정가현 / 팀원: 신종훈
제6회 K-인공지능 제조데이터 분석 경진대회 · 중소·중견기업 재직자 부문 · 과제②

## 내용요약

다이캐스팅 공정 완료 후 최종검사 전에 추가검사 대상을 선별하는 문제를 다룬다. KAMP #42 품질을 주 데이터로, #41 설비 공정·과거이력을 보조 데이터로 연결하고 #40은 별도 온도 제거실험에 사용했다. 기존 고정 분할과 원본을 보존한 탐색 평가에서 공정·센서와20개 공정 event 이상 지난 검사결과를 쓰는 S_FB의 같은 구간 재사용 test AUC는0.7378, AP는0.3845,20% 순위검사 포착은117/272=43.01%였다. 피드백 없는 S 대비 AP+0.0132이지만 구간 재표본 불확실성이0을 포함하고 미래 구간 일관성 기준은 통과하지 못했다. #41 이력 추가와 기존 품질·설비 결합정책의 품질 개선도 입증되지 않았다. 자동 위험 표시·정확한 개별 설명·입력/적용범위 검출·사람 검토 분류를 구현했으며, 현장 수신시각과 실제 비용효과는 도입 전 검증 대상이다.

## 제1장. 기업문제 정의 및 데이터 통합〔20점〕

### 1.1 대상과 품질관리 문제

대상은 익명 중소·중견 다이캐스팅 제조기업의 최종검사 전 추가검사 선별 시나리오다. 실제 협력기업 실증이라고 주장하지 않는다. 데이터의 Product_Type1/2를 대상 제품군으로 구분하며 재질·고객·금형·설비호기·실제 생산일자는 원천으로 확정하지 않는다. 공정은 Shot 단위 주조이며, 완료 공정값을 받은 후 최종검사 결과가 나오기 전에 점수를 산출한다. 생산 이전 예측은 아니다.

품질문제는 여러 불량의 추가검사 누락이다. Short_Shot, Bubble, Exfoliation, Blow_Hole 등을 포함한13종·26개 품질 열 중 하나라도 값>0이면 해당 Shot의 불량으로 정의한다. 유형 중복을 허용하고 불량 열 합을 불량 Shot 수로 쓰지 않는다. _1/_2의 실제 cavity 대응은 현장 인증이 없어 생산수량이나 비용을 두 배로 계산하지 않는다.

현재 승인된 최종검사는 유지하고 추가검사 용량을20%로 가정한다. 동일 데이터의 단순 기준·센서 입력 모델·과거 검사결과·설비정보 추가를 비교한다. 실제 기업 검사율·단가·재작업/폐기비는 확보되지 않았으므로 운영 시나리오와 관측 성과를 구분한다. 기준 KPI는 불량 Shot 포착률, 실제 검사율, 정상 경보 부담, 보류 및 잔량이다.

### 1.2 데이터 역할과 계보

{markdown_table(['데이터','역할·규모','연계와 한계'],[
 ['#42 주조 품질보증','주 데이터:4,617 Shot / 불량1,073','공정·센서·제품·품질 정답; 원본7,535행의 완전중복2,918행 제거'],
 ['#41 주조 설비 예지보전','보조:5,161 공정 event','구간 내 Shot과 공정14 값 일치 확인; 과거이력4개·상태 경보'],
 ['#40 주조 공정최적화','보조 분석:73,612행','독립 공정 안에서 온도군 제거; #41/#42와 행 조인하지 않음']])}

원본CSV → Shot 감소 기준 run 분리 → #42 완전중복 제거 → (run,Shot)1:1 결합 및 공정14 대조 → 과거 이력 생성 → 고정 folds → train 전처리/학습 → validation 선택 → 재사용 test → KPI·판독으로 이어진다. run은 파일 순서에서 만든 연구 구간이며 실제 timestamp가 아니다. 원본·전처리·분할 해시는 등록 기록과 패키지 명세에 보존한다.

#42 적격4,613행, 극소 run5의4행은 기존 제외 역할을 유지한다. #41에 있으나 품질이 없는 행을 정상으로 채우지 않는다. 과거 정책 비교3,395행 중516행 품질 미관측은 별도 경계로 남긴다. 서로 다른 실험 모집단을 하나의 성과로 합치지 않는다.

### 1.3 입력 시점·단위·수집주기

공정14는 속도·압력·상승시간·두께·형체력·사이클·분사시간이다. 센서6은 용해로 값·공기압·냉각수 온도/압력·환경 온도/습도다. 원천 AAS 두 사본은 동일하고 단위122개 중121개가 비어 있으며 일부 타입과CSV 수치가 충돌한다. 변수명만으로 SI 단위나 Hz를 확정하지 않는다. 수집주기·최종검사 전 도착·숫자 상태0/1 의미는 현장 확인 항목이다. 이번 계산은 원자료 값과 공정 event 간격만 사용한다.

기존 shot_position은 품질 파일 행 순서에 의존하므로 새 모델에서 제거했다. 피드백은 같은 run의 공정 순서t에서 event≤t−20의 이미 회신된 품질만 사용한다.20 event를20개 품질행이나 실제 분/초로 바꾸지 않는다. 현재/미래 검사결과·다른 run 정답·상태 정답은 품질 입력으로 금지한다.

## 제2장. AI 모델 개발 및 통합성능 검증〔40점〕

### 2.1 고정 평가와 선정

본 보고서는 양식의6장 구조·배점을 따른다. 과제 원문의 모델35/오류15와 양식의40/10 차이가 있으며 두 항목 합계는50점이다. 실제 수상점수나 수상확률을 추정하지 않는다.

원래 within_run 학습2,579·validation647·test1,387과 forward_run2/3/4/6을 변경하지 않았다. within_run은 각 run 앞부분으로 학습하는 회고 평가라 다른 run의 미래가 학습에 포함될 수 있다. 미래 적용은 forward 결과를 별도로 본다. 이 데이터는 이전 연구에서 이미 평가에 노출됐으며 새로운 독립 검증이 아니다.

입력은 P(공정14), H(P+#41 이력4), S(P+센서6+제품), SH(S+이력4), FB(과거 검사결과만), S_FB, SH_FB다. LogisticRegression, 규제RandomForest, 규제LightGBM, Ordered/시간순 CatBoost, 작은HistGradientBoosting의 고정 설정과3seed를 비교했다. 총525 fit은 후보 탐색량이며 성과가 아니다. 모든 대체·표준화는train에서만 학습하며 내부 무작위 조기중단을 쓰지 않는다.

각 fold·입력별 validation AP의seed 평균으로 모델을 선택하고 선택JSON/해시를 봉인한 뒤 test를 평가했다. 앞선 fold에서 이후 fold 성과로 모델을 고르지 않았다. 임계값은 각 validation 점수80% 분위 바로 위로 고정했다. 이 임계값은 새 구간 검사율20%나 정상FPR2%를 보장하지 않는다.

### 2.2 같은 구간 결과와 제거실험

{metrics_table}

표는3seed 평균이며 SD는 별도CSV에 제공한다. test 불량률272/1,387=19.61%, AP 내부 최소목표는 그2배인0.3922다. S_FB AP0.3845는 이 목표에 미달한다. AUC는 최소0.70을 넘지만 대상권 내부목표0.75에는 미달한다. 연구 판독기는 현재 공정 입력을 포함한 후보 중 sealed validation 최고 S_FB/logistic, 원래 첫seed17로 고정했다. FB 단독은 공정 판독기 대신 기준모델로 남긴다.

S_FB−S의 validation AP는+0.0918,20% 포착률은+8.05%p다. 재사용 test 차이는 AP+0.0132, 포착+1.10%p(117 대114건)로 작다.6개 run block 재표본1,000회의 AP 차이95% 범위는[{unc['lower']:.4f}, {unc['upper']:.4f}]로0을 포함한다. 선택 불확실성과 현장 이동까지 보장하는 신뢰구간은 아니다.

#41 이력의 H−P validation AP+0.0133은 등록+.02에 못 미친다. SH−S는−0.0150, SH_FB−S_FB는−0.0127이다. 동일 모델·seed 쌍의 비교도 별도표에 남겼다. 검사 피드백은 #42 과거 정답의 정보이며 #41 다종융합의 추가가치로 계산하지 않는다. 기존 A/B validation 차이−0.00454 및 기존 실패 결론을 대체하지 않는다.

### 2.3 미래 구간과 피드백 가정

{forward_table}

S_FB는4개 forward validation에서 AP와20% 포착의 음이 아닌 차이가 각각2개 fold뿐이다. 등록한 일관성 채택 기준을 통과하지 못했다. 제품1만 학습한 구간에서 제품2를 평가하는 구조도 있고 제품·시간·run 효과가 섞여 있어 단일 원인으로 단정하지 않는다.

기본 평가는 test 구간에서도 앞선 Shot 정답이20 event 후 회신되는 순차 예측이다. 같은 test의 현재 정답을 입력하지 않지만, 정답이 전혀 없는 일괄 예측과 다르다. 아래는 모델을 바꾸지 않은 민감도다.

{stress_table}

5 event 조건에서 AP가0.3934여도 결과를 본 뒤 기본20 event 가정을 바꾸지 않는다. 회신이 없거나 느릴 때 성능이 낮아진다는 조건부 결과로 보고한다. 실제 수신시각 없이 최종검사 전 가용성을 입증했다고 표현하지 않는다.

## 제3장. 영향요인 및 오류의 정량분석〔10점〕

### 3.1 구간·유형별 실패

{error_table}

표의 오류는 validation에서 고정한0.313415 기준이며 사후20% top-k와 다르다. 전체 TP80·FP106·FN192·TN1,009, 정상FPR106/1,115=9.51%다. 기존 Gate 단독 정상FPR7.83%와도 모집단/목표가 다르다. 높은 위험 표시를 자동 생산중지로 연결하지 않는다.

기존 causal queue의 Q−FIFO 포착 차이는−7.6건이며 run1에서−14.0, 나머지에서+6.4였다. 유형별로 Blow_Hole_1은35→17, Exfoliation_2는20→5, Stain_1은0→18이다. 다중유형이므로 합산하지 않으며 유리한 유형만 선택하지 않는다. 새 모델의 유형별 예측기는 학습하지 않았다.

### 3.2 실제 오탐·미탐과 개별 설명

{example_table}

row_id 사전순 첫 사례를 고른 사후 진단이다. FN은 실제 불량을 놓쳤고 FP는 정상에 높은 점수를 냈다. 사례의 성공률을 전체 성능으로 확대하지 않는다.

선형 모델은 train 대체·표준화 값×계수와 절편을 합쳐 실제log-odds를 정확히 재구성한다. q42_r0_s1000의 점수는{quality['score']:.6f}이며 기여 상위 항목은 아래와 같다. 양/음 기여는 그 모델의 예측 방향이고 물리 원인·운전 변경 효과가 아니다.

{markdown_table(['변수','원자료 값','log-odds 기여'],[[x['feature'],x['input_value'],f'{x["contribution"]:+.4f}'] for x in top])}

24개의 고정 순서 실제 입력에서 저장 예측과 runtime 최대차는5.6e−17이었다. 현재라벨·미래피드백·입력누락·미경험제품의 기능 검사는 별도다. 기능 검증 개수를 모델 정확도로 쓰지 않는다.

### 3.3 고정 변수쌍·공동지지

High_Velocity×Casting_Pressure를 사전 고정했다. train 분위3×3 cell에서 제품별 train30·test20행 이상일 때 실제행의 다른 입력을 고정하고 두 변수25/75분위 교차4점의 차이를 계산했다. 조건 추천은 하지 않는다.

within_run에서 입력군별6개 제품-cell이 하한을 만족했다. S_FB의 절대 점수 교호차는0.000060, log-odds 교호차는 수치오차 수준으로 선형모델 구조에 부합한다. SH/RF 교호차0.003841도 인과효과는 아니다. forward의 지지는 입력군별1개cell에 불과했다.

범위·공동지지·피드백 점검에서1,387행 중{manual}행({manual/1387*100:.2f}%)에 경고가 발생했다. 환경값·누적 피드백 수의 범위 초과가 많았다. 경고행을 성능 분모에서 빼지 않고 사람 검토로 분류한다.

## 제4장. 현장 적용 기본설계 및 KPI 개선효과〔10점〕

### 4.1 자동 판독과 사람의 조치

입력수신 → 필드/순서/라벨시점 검사 → 품질점수·개별설명 → 학습범위·공동지지 경고 → 추가검사 검토/기존절차 유지/담당자 검토 순서로 동작한다. 명시된 과거 공정이력으로 기존 #41 Gate도 별도 계산해 품질·설비 담당자 공동 검토를 표시한다. 처음으로 validation 조건을 충족했던 동결checkpoint3/seed17을 사용하며 현장 경보율을 보증하지 않는다.

현재/미래정답, 같은 event 중복, 다른run 이력, 미도착 피드백은 거절한다. 현재 공정·센서가 없으면 점수를 만들지 않는다. 지원 범위를 벗어나거나 과거 회신이 없으면 자동으로 사람 검토로 돌린다. 정상 표시도 기존 최종검사를 면제하지 않는다. 제어기·MES 명령·자동 생산중지·폐기·설정 변경 인터페이스는 없다.

실제 현장에서는 run 시작·공정시각·완료시각·품질 도착시각·검사 용량을 기록하고 승인된 shadow pilot을 먼저 수행한다. 생산중지와 재작업은 현행 품질규정·담당자 확인 후 결정한다. 입력 계약을 검증하는 기능과 현장 입력원이 그 계약을 충족한다는 증거는 구분한다.

### 4.2 검사 용량의 관측 성과

새 순위검사에서277/1,387=19.97%를 선택하면 S_FB는117/272=43.01%, S는114/272=41.91%를 포착한다. 무작위 기대 포착은272×277/1,387=54.32건이다. 이 값은 사후batch 순위 진단이며 실제 도착 대기열 정책의 개선이 아니다. 확정 검사비·대기시간·불량 감소량으로 바꾸지 않는다.

기존 동결 causal queue는 공통 제공기회677, 실제검사FIFO/Q675·GQ677이었다. 관측 품질2,879행·불량505 중 FIFO113(22.376%)·Q105.4(20.871%)·GQ102.2(20.238%)를 포착했다. GQ의 상태에피소드 검사도달8/15는Q1/15보다 높지만, 품질 포착은 줄었다. 관측가능 에피소드로 한정하면GQ7/14·Q0/14이며 전체분모와 구분한다. 품질미관측516행·보류409행·종료잔량241행을 보존한다.

Gate 단독은 관측20개 중17.6개 평균 탐지, 전체21개 에피소드, 정상FPR7.83%다. 탐지율만으로 정상FPR≤2% 목표 달성을 선언하지 않는다. queue 자동경보 정상FPR1.091%는 별도 모집단이며 보류포함 정상개입10.868%를 함께 보고한다.

### 4.3 조건부 비용 효과

실제 단가가 없어 검사비1단위, 불량누락비c단위로 놓고 손실=검사수+c×미포착불량으로 계산한다. 추가검사가 완전하고 불량누락비가 일정하다는 가정이며 재작업·고정인건비·설비중단·실제 폐기효과를 측정하지 않았다. 경고에 따른 실제 사람검토 비용도 미포함이다.

{cost_table}

이 표는 고정 임계값 원점수의 가상검사(S78건/FN235, S_FB186건/FN192)이며 실제 판독기의 보류 처리를 적용한 운영 KPI가 아니다. S_FB가 검사108건을 더 쓰고 미포착43건을 줄이므로 손익분기 비율은108/43=2.51이다. 비율1에서는 비용이 더 크고 비율5에서는8.54% 낮다. 실제 비용절감이나 불량률 감소를 확정한 결론은 아니다.

## 제5장. 창의성 및 확장성〔10점〕

이 연구의 차별점은 다종데이터의 단순 결합 수보다 입력 가용성·위험 설명·검사 자원 경쟁·판단불가를 같은 흐름으로 검증한 데 있다. #41 정보가 품질에 도움되지 않은 경우도 버리지 않고 제거실험과 의사결정 비교로 제시한다. 검사 피드백은 현실적인 운영 가정에 따라 효과가 달라지는 별도 정보원으로 구분한다.

#40 정상압력 자료에서는 금형온도6개를 제거하면AUC0.8673→0.7458, 날짜block 차이95%범위[0.0777,0.1739]였다. 이는 해당 공정의 변수 가치 근거이며 #42 성능개선·두 원시데이터 융합효과·인과효과가 아니다. 주 압력 방향의 불일치도 있어 공장 간 전이 성공을 주장하지 않는다.

다른 현장에 재사용할 것은 입력/시각 계약, 과거회신 처리, train-only 전처리, 설명재구성, 비교·보류·감사 구조다. 새 제품·금형·설비에서는 변수정의/단위, 결합키, 품질검사 기준, 수신시각을 재검증하고 미노출 시간순 자료로 모델·임계값·검사비를 평가해야 한다. 제품2 미학습 문제나 환경 이동을 모형만으로 해결했다고 가정하지 않는다.

## 제6장. 코드 구성 및 재현성〔10점〕

소스 ZIP에는 원본 3종, 전처리·고정분할, 코드·잠금환경, 사전계획·설정, validation 후보표/선정기록, test 예측, 대표모델·입력 예제·README를 넣는다. 결과표에는 분모·역할·fold·seed·입력군이 있다. 원래 결과를 덮어쓰지 않고 새 출력은 reports/oct06_research에 분리했다.

추론: python -m castguard.submission_reader --input examples/submission_reader/shots.json --output demo.json --html demo.html

검사: python -m pytest -q tests/test_oct06_research.py tests/test_submission_reader.py

연구 재현: python reproduce_submission.py --output verification_runs/research_replay --jobs 4

재현은 동일 등록 설정·분할의 525 fit을 새 경로에 수행하고 validation 선택을 다시 봉인한다. 빠른 판독은 포함한 모델을 사용한다. 임의 외부 joblib을 로드하는 서비스가 아니며 신뢰한 로컬 패키지 해시를 확인한다. 이 보고서의 test 예측파일은 research_reader_predictions.csv와 selected_predictions.parquet다. 현재 자료로 다시 학습해도 독립자료가 생기는 것은 아니다.

입력/설명 재현, 누락/현재·미래정답 거절, 정책분모, 최종PDF·PPTX 렌더와 ZIP 재현을 검수한다. 실행기록과 최종 파일해시는 검수명세에서 확인한다. 과거 시험통과를 새 최종본 검수로 대신하지 않는다.

## 부록 A. 근거와 해석 범위

핵심 결과: reports/oct06_research/summary.csv, selected_metrics.csv, comparisons.csv, same_model_validation_ablation.csv, feedback_sensitivity.csv, adoption_decisions.json, reader_uncertainty.json. 새 연구는 원래 목표나실패 수치를 소급 변경하지 않았다.

조건/자동 판독: condition_errors.csv, joint_support.csv, pair_interactions.csv, diagnostic_examples.csv, reader_support_audit.csv, demo_verification.json. 기존 queue: reports/oct03_round7/group_metrics.csv 및 reports/oct03_queue_review/pooled_at20.csv. 기존 #40: reports/oct02/ablation_summary.csv 및 bootstrap_intervals.csv.

원천: 중소벤처기업부·KAMP·스마트제조혁신추진단, 주조 품질보증 / 주조 설비 예지보전 / 주조 공정최적화 AI 데이터셋. 원천 문서의 변수·단위·물리키 불확실성은 그대로 표시했다. 방법: scikit-learn1.7.2 공식HistGradientBoostingClassifier 문서, CatBoost 공식training-parameters/common의Ordered·has_time 설명. 새 기법의 일반적 우수성을 이 데이터 성과로 대신하지 않았다.

상기 본인(팀)은 위 내용과 같이 결과보고서를 제출합니다.
팀장: 정가현 (서명: ____________________) / 팀원: 신종훈 (서명: ____________________)
작성일: {datetime.now(timezone(timedelta(hours=9))):%Y년 %m월 %d일}. 서명과 포털 접수는 참가팀이 실제로 완료해야 한다.
'''
    return text


def render(text):
    pdfmetrics.registerFont(TTFont('Body','C:/Windows/Fonts/batang.ttc',subfontIndex=0))
    pdfmetrics.registerFont(TTFont('Bold','C:/Windows/Fonts/malgunbd.ttf'))
    styles={
        'p':ParagraphStyle('p',fontName='Body',fontSize=14,leading=22.4,wordWrap='CJK',spaceAfter=11),
        'h2':ParagraphStyle('h2',fontName='Bold',fontSize=18,leading=27,wordWrap='CJK',spaceAfter=17,keepWithNext=True),
        'h3':ParagraphStyle('h3',fontName='Bold',fontSize=14,leading=22.4,wordWrap='CJK',spaceBefore=13,spaceAfter=9,keepWithNext=True),
        'cell':ParagraphStyle('cell',fontName='Body',fontSize=10.4,leading=16.5,wordWrap='CJK'),
        'small':ParagraphStyle('small',fontName='Body',fontSize=10,leading=16,wordWrap='CJK',spaceAfter=9),
        'title':ParagraphStyle('title',fontName='Bold',fontSize=25,leading=36,wordWrap='CJK',spaceAfter=24)
    }
    story=[];e=html.escape
    summary=text.split('## 내용요약\n\n')[1].split('\n\n## 제1장')[0]
    story.extend([Paragraph('제6회 K-인공지능 제조데이터 분석 경진대회',styles['small']),Spacer(1,24),
                  Paragraph('CastGuard<br/>근거를 설명하는<br/>품질검사 의사결정 지원',styles['title']),
                  Paragraph('중소·중견기업 재직자 부문 · 과제②',styles['p']),
                  Paragraph(TEAM,styles['h3']),Paragraph('팀장 정가현 · 팀원 신종훈',styles['p']),Spacer(1,22),
                  Paragraph('내용요약',styles['h3']),Paragraph(e(summary),styles['small']),
                  Spacer(1,12),Paragraph('최종검사 전 입력을 전제로 한 오프라인 연구·현장 적용 기본설계<br/>모든 신규 성능은 이미 공개된 데이터의 탐색 재사용 평가',styles['small'])])
    body=text[text.index('## 제1장'):];lines=body.splitlines();i=0
    while i<len(lines):
        line=lines[i].strip()
        if not line:i+=1;continue
        if line.startswith('## '):story.extend([PageBreak(),Paragraph(e(line[3:]),styles['h2'])]);i+=1;continue
        if line.startswith('### '):story.append(Paragraph(e(line[4:]),styles['h3']));i+=1;continue
        if line.startswith('|'):
            rows=[]
            while i<len(lines) and lines[i].strip().startswith('|'):
                rr=[v.strip() for v in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r'[: -]+',v) for v in rr):rows.append(rr)
                i+=1
            cols=len(rows[0]);width=481.9
            ratios={3:[.23,.32,.45],4:[.24,.24,.26,.26],5:[.28,.18,.18,.16,.20]}.get(cols,[1/cols]*cols)
            table=Table([[Paragraph(e(v),styles['cell']) for v in row] for row in rows],colWidths=[width*r for r in ratios],repeatRows=1,hAlign='LEFT')
            table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e4edf4')),('LINEBELOW',(0,0),(-1,0),.7,colors.HexColor('#25455e')),
                ('LINEBELOW',(0,1),(-1,-1),.3,colors.HexColor('#c8d4dd')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8)]))
            story.extend([table,Spacer(1,13)]);continue
        story.append(Paragraph(e(line),styles['p']));i+=1
    def footer(can,doc):
        can.setFont('Body',9);can.setFillColor(colors.HexColor('#53657b'))
        can.drawString(56.69,24,'CastGuard · 과제② · '+TEAM);can.drawRightString(A4[0]-56.69,24,str(doc.page))
    tmp=BUILD/'report_body.pdf'
    SimpleDocTemplate(str(tmp),pagesize=A4,leftMargin=56.69,rightMargin=56.69,topMargin=42.52,bottomMargin=42.52,
        title='CastGuard: 근거를 설명하는 품질검사 의사결정 지원',author=TEAM).build(story,onFirstPage=footer,onLaterPages=footer)
    # Entire unmodified survey image on landscape page; separately preserve original PNG bytes.
    survey=BUILD/'survey_appendix.pdf';can=canvas.Canvas(str(survey),pagesize=landscape(A4));w,h=landscape(A4)
    can.setFont('Bold',18);can.drawString(40,h-48,'부록 B. 설문조사 완료 화면')
    can.setFont('Body',10);can.drawString(40,h-70,'참가팀이 제공한 원본 화면을 그대로 첨부했습니다.')
    can.drawImage(str(ROOT/'docs/설문조사완료.png'),40,35,width=w-80,height=h-125,preserveAspectRatio=True,anchor='c')
    can.save()
    writer=PdfWriter();writer.append(tmp);writer.append(survey);writer.add_metadata({'/Title':'CastGuard 품질검사 의사결정 지원','/Author':TEAM})
    with (OUT/'CastGuard_report.pdf').open('wb') as stream:writer.write(stream)
    shutil.copy2(ROOT/'docs/설문조사완료.png',OUT/'설문조사완료.png')
    p=PdfReader(OUT/'CastGuard_report.pdf');return len(p.pages)


def main():
    BUILD.mkdir(parents=True,exist_ok=True);OUT.mkdir(exist_ok=True)
    text=content();(BUILD/'CastGuard_report.md').write_text(text,encoding='utf-8')
    pages=render(text)
    # Compact document preview preserves every section as text, PDF is authoritative layout.
    preview='<meta charset="utf-8"><style>body{max-width:950px;margin:40px auto;font:17px/1.8 "Malgun Gothic";white-space:pre-wrap}</style><body>'+html.escape(text)+'</body>'
    (BUILD/'report_preview.html').write_text(preview,encoding='utf-8')
    shutil.copy2(E/'demo.html',OUT/'CastGuard_demo.html')
    print('report pages:',pages)


if __name__=='__main__':main()
