"""Update the JH submission from registered fusion results and replayed team evidence."""
from pathlib import Path
import html
import json
import re
import shutil

import pandas as pd

import build_oct06_submission as old

ROOT = Path(__file__).resolve().parent
BUILD = ROOT/'reports/oct08_submission'
OUT = BUILD/'candidate'
FUSION = ROOT/'reports/oct08_fusion'
TEAM = ROOT/'reports/oct08_team_replay'


def rank_auc(y, score):
    ranks=score.rank(method='average')
    positive=y.eq(1);n=int(positive.sum());negative=len(y)-n
    return (ranks[positive].sum()-n*(n+1)/2)/(n*negative)


def spacing(text):
    # Only visible prose: preserve literal paths, commands, identifiers and decimals.
    replacements = {'공정·센서와20':'공정·센서와 20', 'AUC는0.':'AUC는 0.', 'AP는0.':'AP는 0.',
        '원시데이터':'원시 데이터', '다종데이터':'다종 데이터', '검사결과':'검사 결과', '추가검사':'추가 검사',
        '최종검사':'최종 검사', '공정조건':'공정 조건', '사람검토':'사람 검토', '정상FPR':'정상 FPR',
        '개별설명':'개별 설명', '수신시각':'수신 시각', '품질판정':'품질 판정', '설명재구성':'설명 재구성',
        '학습범위':'학습 범위', '적용범위':'적용 범위', '고정분할':'고정 분할', '판단불가':'판단 불가',
        '누락정답':'누락 정답', '공동지지':'공동 지지', '과거회신':'과거 회신', '원본CSV':'원본 CSV',
        '라벨시점':'라벨 시점', '필드/순서':'필드·순서', '모든선택':'모든 선택', '최종PDF':'최종 PDF',
        '원래 목표나실패':'원래 목표나 실패', '표는3seed':'표는 3 seed', 'test 불량률272':'test 불량률 272',
        '과제②':'과제 ②', '기존모델':'기존 모델', '새 점수':'새 점수'}
    replacements.update({'입력수신':'입력 수신','품질점수':'품질 점수','공정이력':'공정 이력',
        '미래정답':'미래 정답','생산중지':'생산 중지','설정변경':'설정 변경','적용범위':'적용 범위',
        '범위초과':'범위 초과','품질미관측':'품질 미관측','관측가능':'관측 가능','상태에피소드':'상태 에피소드',
        '검사도달':'검사 도달','첫seed':'첫 seed','불량률의':'불량률의','추가가치':'추가 가치',
        '예측오차':'예측 오차','기준모델':'기준 모델','선형모델':'선형 모델','선택모델':'선택 모델',
        '개별기여':'개별 기여','최종모델':'최종 모델','입력계약':'입력 계약','현장효과':'현장 효과',
        '비용절감':'비용 절감','원점수':'원 점수','검사비율':'검사 비율','정량분석':'정량 분석',
        '입력누락':'입력 누락','미경험제품':'미경험 제품','현재라벨':'현재 라벨','미래피드백':'미래 피드백',
        '실제행':'실제 행','판독기':'판독기','검사결과':'검사 결과','공정시각':'공정 시각','완료시각':'완료 시각',
        '통합성능':'통합 성능','개선효과':'개선 효과','train30':'train 30','test20':'test 20',
        '다른run':'다른 run','미학습문제':'미학습 문제'})
    for a,b in replacements.items():
        text = text.replace(a,b)
    lines = []
    for line in text.splitlines():
        if 'python ' not in line:
            literals=[]
            def protect(m):
                literals.append(m.group());return f'ZZPATH{len(literals)-1}ZZ'
            line=re.sub(r'[A-Za-z0-9_./-]+\.(?:csv|parquet|py|json|md|html|joblib)',protect,line)
            line = re.sub(r'(?<!제)(?<=[가-힣])(?=[0-9])',' ',line)
            line = re.sub(r'(?<=[0-9])(?=seed|event|fold|fit|block)',' ',line)
            line = re.sub(r'(?<=[가-힣])(?=train|test|validation|AP|AUC|FPR|CSV|PDF|PPTX)',' ',line)
            line = re.sub(r'\b(AP|AUC|FPR|TP|FP|FN|TN|FIFO|GQ|Q|train|test|run|seed|event|checkpoint)(?=[0-9+−])',r'\1 ',line)
            line = re.sub(r'(?<=[가-힣])\.(?=[가-힣0-9])','. ',line)
            line = re.sub(r'(?<=,)(?=[가-힣A-Za-z])',' ',line)
            line = re.sub(r',(?=\d{1,2}%)',', ',line)
            for i,literal in enumerate(literals):line=line.replace(f'ZZPATH{i}ZZ',literal)
        lines.append(line)
    return '\n'.join(lines)+'\n'


def content():
    s = pd.read_csv(FUSION/'summary.csv',dtype={'fold':str})
    w = s[s.scheme=='within_run']
    checks = json.loads((TEAM/'verification.json').read_text())
    assert all(x['matched_to_rounding'] for x in checks.values())
    assert json.loads((FUSION/'run_state.json').read_text())['status']=='completed'
    text = old.content()
    summary = ('같은 구간 재사용 test 1,387 Shot에서 추가 검사 대상으로 상위 277건(19.97%)을 선정해 '
        '불량 272건 중 117건(43.01%)을 포착했다. 동일 검사 수의 무작위 선택 기대값 대비 약 2.15배이며, '
        'S_FB 모델의 AUC는 0.7378, AP는 0.3845다. 과거 검사 결과를 추가하기 전보다 AP가 0.0132 높았다. '
        '이 순위와 개별 기여 설명, 입력·학습범위 경고를 실제 판독 도구로 연결했다. '
        'KAMP #42 품질을 중심으로 #41 설비 이력과 #40 전이 점수를 조합한 네 가지 제거실험을 수행했고, '
        '팀의 적응형 설비 Gate 및 불량 유형별 모델을 재현해 적용 단계별 근거를 보강했다. '
        '새 보조 입력은 사전에 정한 품질 개선 기준에 미달해 기존 판독 모델을 유지한다. '
        '사후 순위검사 결과와 현장 운영효과는 구분하며, 미래 구간 성능과 실제 수신 시각·비용은 추가 검증 대상이다.')
    text = re.sub(r'(?<=## 내용요약\n\n).*?(?=\n\n## 제1장)',lambda _:summary,text,flags=re.S)
    text = text.replace('통합성능 검증〔40점〕','통합성능 검증〔35점〕').replace('오류의 정량분석〔10점〕','오류의 정량분석〔15점〕')
    text = re.sub(r'본 보고서는 양식의6장 구조·배점을 따른다\..*?실제 수상점수나 수상확률을 추정하지 않는다\.',
        '공식 보고서 양식의 6장 구조를 유지하고, 장 제목의 배점은 과제공개 원문의 모델 35점·오류분석 15점을 따른다. 양식의 40점·10점 표기와 차이가 있으나 두 항목의 합계는 50점으로 같다.',text)
    text = text.replace('| #40 주조 공정최적화 | 보조 분석:73,612행 | 독립 공정 안에서 온도군 제거; #41/#42와 행 조인하지 않음 |',
        '| #40 주조 공정최적화 | 보조 전이 연구 및 온도 분석: 73,612행 | train 분위 정렬 후 위험 점수 전이; 온도 제거는 해당 공정 내 별도 분석 |')
    labels = {'S':'#42', 'SH':'#42 + #41', 'S_T':'#42 + #40', 'SH_T':'#42 + #41 + #40'}
    def table(model,suffix=''):
        rows=[]
        for rep,label in labels.items():
            v=w[(w.representation==rep+suffix)&(w.model==model)&(w.role=='validation')].iloc[0]
            t=w[(w.representation==rep+suffix)&(w.model==model)&(w.role=='test')].iloc[0]
            rows.append([label,f'{v.ap:.4f}',f'{t.ap:.4f}',f'{t.auc:.4f}',f'{t.capture20*100:.2f}%'])
        return old.markdown_table(['데이터 조합','val AP','test AP','test AUC','20% 포착'],rows)
    uc = pd.DataFrame(json.loads((FUSION/'uncertainty.json').read_text()))
    u=uc[(uc.model=='random_forest')&(uc.added=='S_T')&(uc.base=='S')].iloc[0]
    source=pd.read_csv(FUSION/'source_metrics.csv');source_auc=source[source.role=='test'].auc.mean()
    tp=pd.read_csv(FUSION/'transfer_metrics.csv');tp=tp[(tp.scheme=='within_run')&(tp.role=='test')]
    transfer_auc=tp.auc.mean()
    fusion=f'''### 2.3 네 가지 데이터 조합의 직접 비교

팀 피드백의 공통 개념 분위 정렬 아이디어를 기존 JH의 고정 분할·입력 시점 계약에 맞춰 재구현했다. #42 단독 S, #41 이력 추가 SH, #40 전이 점수 추가 S_T, 모두 추가 SH_T를 동일한 규제 RF와 seed 17/29/43으로 비교했다. 아래 주 표는 모델을 RF로 고정한 3 seed 평균이며, 앞 절의 입력별 validation 선택모델 표와 목적이 다르다. 검사 수는 모두 277/1,387, 불량 분모는 272다.

{table('random_forest')}

#40은 행을 조인하지 않고 주입압력·사이클·강도/형체력·비스킷 두께·냉각수 온도의 5개 대응 가정을 고정했다. 각 공정의 train에서만 중앙값과 경험누적분포를 학습했다. #40의 기존 정상압력 chronological train에서 학습한 RF가 내는 점수 1개를 #42의 각 fold에 전달한다. mechanical_strength와 Clamping_Force를 포함한 의미·단위 대응은 미확인 가정이며, 분위 정렬이 물리적 동등성을 보장하지 않는다. source 모델이 대상 운영 전에 확보돼 있다는 시나리오다.

S_T−S의 validation AP 차이는 +0.0038로 기존 +0.02 기준에 미달했고, test AP 차이는 −0.0031이었다. test 6 run 블록 재표본 1,000회의 AP 차이 95% 범위는 [{u.ap_gain_low:.4f}, {u.ap_gain_high:.4f}]다. source 자체 test AUC는 {source_auc:.4f}, #42로 옮긴 점수 단독 AUC는 {transfer_auc:.4f}다. 공정 안에서의 신호와 다른 공정으로 옮긴 신호의 가치를 구분한다.

검사 피드백을 추가한 동일 RF의 네 조합도 분리해 확인했다. 피드백은 기본 20 공정 event 지연의 #42 과거 정답이며 #41/#40 융합효과로 계산하지 않는다.

{table('random_forest','_FB')}

모델 의존성을 확인한 로지스틱의 피드백 없는 네 조합 결과는 다음과 같다. 표본과 분할은 동일하다.

{table('logistic')}

두 모델·피드백 유무·5개 분할의 결과를 모두 보존했다. 네 가지 입력 추가 비교 각각에 기존 validation AP +0.02, 포착 +5%p, 적격 forward validation 2개 이상에서 음이 아닌 AP/포착 차이를 적용했지만 채택 기준을 충족한 비교는 없었다. test에서 유리한 일부 포착 수치로 최종 모델을 바꾸지 않았다. 이 결과는 데이터 조합별 시도와 한계를 직접 측정한 성과이며 품질 성능 향상 성공을 뜻하지 않는다.

### 2.4 미래 구간과 피드백 가정'''
    text=text.replace('### 2.3 미래 구간과 피드백 가정',fusion)
    types=pd.read_csv(TEAM/'type_summary.csv')
    tt=old.markdown_table(['불량 유형','양성 / 1,387','AUC','AP','불량률'],[
        [r.target,int(r.test_positive),f'{r.test_auc:.4f}',f'{r.test_ap:.4f}',f'{r.prevalence*100:.2f}%'] for r in types.itertuples()])
    text=text.replace('새 모델의 유형별 예측기는 학습하지 않았다.',
        '아래 팀 보조 연구에서는 불량 유형별 모델을 별도로 재현했다.')
    text=text.replace('### 3.2 실제 오탐·미탐과 개별 설명',f'''### 3.2 팀의 불량 유형별 모델 재현

팀원이 개발한 add 90402e0의 고정 모델·5 seed를 동일 코드와 데이터로 다시 학습해 원래 반올림 표와 일치함을 확인했다. 같은 구간 test 1,387건의 결과다. Etc는 주요 네 유형 이외 불량들의 합집합이며 유형 중복이 있으므로 양성 수를 합산하지 않는다.

{tt}

작은 양성 수에서는 높은 AUC만으로 검사 효용을 판단하기 어렵다. AP와 불량률을 함께 제시했다. 이 보조 연구는 품질 행 순번과 20개 품질 행 지연의 과거 회신을 쓰는 A_FB 입력이며, 공정 event 지연으로 재구현한 현재 판독기와 별도다. 현장 순번의 가용성과 유형별 미래 구간 성능은 미검증이며 현재 판독기가 이 다섯 유형을 자동 진단한다는 뜻은 아니다.

### 3.3 실제 오탐·미탐과 개별 설명''').replace('### 3.3 고정 변수쌍·공동지지','### 3.4 고정 변수쌍·공동지지')
    gs=pd.read_csv(TEAM/'gate_summary.csv',dtype={'fold':str})
    g=gs[(gs.policy=='적응형')&(gs.scheme!='run_holdout')]
    gt=old.markdown_table(['평가 구간','탐지 / 관측 / 전체','정상 행','평균 오경보','정상 FPR'],[
        ['같은 구간' if r.scheme=='within_run' else '미래 run '+r.fold,
         f'{r.detected_within_k:.0f} / {r.episodes:.0f} / {r.all_episodes_in_test_boundaries:.0f}',
         int(r.normal_rows),f'{r.false_positive:.1f}',f'{r.false_stop_rate*100:.2f}%'] for r in g.itertuples()])
    text=text.replace('### 4.3 조건부 비용 효과',f'''### 4.3 팀의 적응형 설비 Gate와 경보 부담

add 팀의 구간 상대값·적응형 임계값 Gate를 고정한 그대로 5 seed 재현했다. 현재 공정값을 같은 run의 직전 30행 중앙값과 비교하는 입력을 사용한다. 적응형 임계값은 과거 정상 상태가 20개 평가 행 지연 후 확인되고 정상 이력이 30개 이상이라는 가정을 요구한다. 라벨 없는 배치 적용이나 실제 설비 제어 성과가 아니다.

{gt}

탐지는 관측된 에피소드의 첫 3 Shot 이내 경보를 뜻한다. 전체 분모는 해당 test run/Shot 경계 안의 미평가 에피소드까지 포함하며, 같은 구간은 관측 9개·전체 10개다. 동일 모집단의 고정 Gate는 정상 FPR 2.68%, 적응형은 2.29%로 0.39%p 감소했고 탐지 8개는 유지됐다. 기존 JH Gate의 20/21 에피소드 및 정상 FPR 7.83%와는 직접 우열을 비교하지 않는다. 적응형도 원래 정상 FPR 2% 목표에는 미달하며 미래 run 3에서는 0/3으로 실패했다. 예열 상태 코드의 현장 의미와 정상 회신 가용성은 도입 전에 확인해야 한다.

### 4.4 조건부 비용 효과''')
    text=text.replace('이 연구의 차별점은 다종데이터의 단순 결합 수보다 입력 가용성·위험 설명·검사 자원 경쟁·판단불가를 같은 흐름으로 검증한 데 있다.',
        '이 연구는 세 원시 데이터의 네 조합, 지연 검사 피드백, 설비 상태 경보를 각각 검증하고 위험 설명과 추가 검사 판단으로 연결했다. 동일 구간에서 검사 자원의 약 20%로 불량 43.01%를 포착하는 연구 판독과 정확한 개별 기여 설명을 제공한다.')
    text=text.replace('주 압력 방향의 불일치도 있어 공장 간 전이 성공을 주장하지 않는다.',
        '이 관측은 금형 열상태 수집을 후속 후보로 제안할 근거다. #42에서 온도가 빠진 것이 성능 한계의 원인이라는 인과 해석은 하지 않는다. 네 조합 실험도 현재의 공통 변수 전이 방식이 품질 개선 기준에 미달함을 확인했다.')
    text=text.replace('빠른 판독은 포함한 모델을 사용한다.',
        '추가한 네 조합 실험은 python -m castguard.oct08_fusion --output verification_runs/fusion_replay --jobs 4 --reproduction 으로 재현한다. 팀 보조 모델은 python verify_oct08_team.py --output verification_runs/team_replay 로 재현한다. 빠른 판독은 기존에 포함한 모델을 사용한다.')
    text=text.replace('핵심 결과: reports/oct06_research/summary.csv',
        '10/8 추가 근거: reports/oct08_fusion의 summary.csv, paired_comparisons.csv, decisions.json, uncertainty.json, predictions.parquet; reports/oct08_team_replay의 gate_summary.csv, type_summary.csv, verification.json. 고정 계획은 docs/OCT08_FUSION_PROTOCOL.md다.\n\n핵심 결과: reports/oct06_research/summary.csv')
    return spacing(text)


def main():
    BUILD.mkdir(parents=True,exist_ok=True);OUT.mkdir(exist_ok=True)
    old.BUILD,old.OUT=BUILD,OUT
    text=content()
    (BUILD/'CastGuard_report.md').write_text(text,encoding='utf-8')
    pages=old.render(text)
    (BUILD/'report_preview.html').write_text('<meta charset="utf-8"><style>body{max-width:1000px;margin:36px auto;font:17px/1.8 "Malgun Gothic";white-space:pre-wrap}</style><body>'+html.escape(text)+'</body>',encoding='utf-8')
    demo=(ROOT/'reports/oct06_research/demo.html').read_text(encoding='utf-8')
    notice='''<section style="padding:20px;background:#e7eff8"><h2>10/8 팀 연구 통합</h2>
<p>같은 구간 재사용 test: AUC 0.7378 · AP 0.3845 · 상위 277/1,387 검사로 불량 117/272(43.01%) 포착.</p>
<p>네 가지 데이터 조합의 추가 입력은 개선 기준에 미달해 기존 판독 모델을 유지합니다. 팀의 적응형 Gate와 유형별 모델은 별도 코드로 재현해 보고서에 통합했습니다. 아래 11건 판독의 모델을 바꾼 것은 아닙니다.</p></section>'''
    (OUT/'CastGuard_demo.html').write_text(demo.replace('<h1>',notice+'<h1>',1),encoding='utf-8')
    print('report pages',pages)


if __name__=='__main__':main()
