"""Produce a template-aligned editable source with explicit unsupported native formatting."""
from pathlib import Path
from hashlib import sha256
import json,re,html
import pandas as pd
from report_evidence import collect,fill,sha
ROOT=Path(__file__).resolve().parent

def build(root=ROOT):
    out=root/'reports/submission_round6';out.mkdir(exist_ok=True)
    facts=collect(root)
    source='reports/submission_round6/baselines_final/baseline_summary.csv'
    frame=pd.read_csv(root/source).set_index('policy')
    for policy,row in frame.iterrows():
        for field,suffix,mul,fmt in [('capture','CAP',100,'.3f'),('hits','HITS',1,'.1f'),('Q_gain_pp','QG',1,'.3f'),('GQ_gain_pp','GQG',1,'.3f'),('capture_p025','P025',100,'.3f'),('capture_p975','P975',100,'.3f')]:
            value=float(row[field]);facts[policy+'_'+suffix]={'value':value,'display':format(value*mul,fmt),'unit':'percent' if 'capture' in field else 'percentage points' if 'gain' in field else 'count','source':source,'selector':f'policy={policy}; {field}','sha256':sha(root/source)}
    original=(root/'docs/REPORT_DRAFT_TEMPLATE.md').read_text(encoding='utf-8')
    body=original[original.index('## 제1장'):]
    body=body.replace('### 검사 대기와 적용 범위','### 기업문제 정의').replace('### 데이터 역할과 계보','### 데이터 선정').replace('### 연결 근거와 허용하지 않은 연결','### 통합설계 및 데이터 계보')
    body=body.replace('### 품질 단독과 이력 결합의 전후 비교','### 보조 데이터 추가 전후 비교').replace('### 상태 경보와 품질 검사의 의사결정 결합','### 독립 제거실험과 의사결정 결합')
    weights=[20,40,10,10,10,10]
    body=re.sub(r'## 제([1-6])장 (.+)',lambda m:f'## 제{m[1]}장. {m[2]}〔{weights[int(m[1])-1]}점〕',body)
    insert='''### 단순 검사 기준 대비 실질 이득

같은 바깥 개발 구간과 누적 20% 검사 용량에서 단순 기준을 추가로 점검했다. 정책은 결과 선택에 사용하지 않고 과거 결과를 본 뒤 고정한 설명용 비교다. 평가 라벨은 점수 생성에 넣지 않았다. 동일 입력결손 보류와 동일 품질점수 가용 행을 유지했다. 모든 단순 기준은 675건을 검사하고 미처리 보류는 241건이다.[J01]

| 기준 | 포착 양성 Shot | 포착률 | Q와의 차이 |
|---|---|---|---|
| FIFO 먼저 도착한 순서 | {{FIFO_HITS}} | {{FIFO_CAP}}% | Q가 {{FIFO_QG}}%p |
| 과거 제품별 빈도 | {{RECENT_PRODUCT_RATE_HITS}} | {{RECENT_PRODUCT_RATE_CAP}}% | Q가 {{RECENT_PRODUCT_RATE_QG}}%p |
| 무작위 위험도 100회 평균 | {{RANDOM_HITS}} | {{RANDOM_CAP}}% | Q가 {{RANDOM_QG}}%p |
| 공정값 이탈 경험 규칙 | {{PROCESS_DEVIATION_HITS}} | {{PROCESS_DEVIATION_CAP}}% | Q가 {{PROCESS_DEVIATION_QG}}%p |

FIFO와 과거 빈도는 113/505개를 포착해 Q의 {{Q_CAPTURE}}%, GQ의 {{GQ_CAPTURE}}%보다 높았다. 최근빈도는 nested fit의 마지막 100개 관측에서 제품별 양성비율을 계산하고 이후 고정했다. 실제 검사결과 도착시간이 없어 평가 중 정답을 받거나 비율을 갱신하지 않았다. 동점은 먼저 도착한 순서로 처리했다. 두 기준의 결과가 같다는 사실을 별개의 성능 개선 두 건으로 세지 않는다.

무작위100회의 2.5~97.5백분위는 {{RANDOM_P025}}~{{RANDOM_P975}}%다. Q는 그 범위 안에 있다. 이 범위는 고정 데이터에서 난수 정책의 변동이며 미래 일반화 신뢰구간이나 유의성 검정이 아니다. 무작위 평균보다 조금 높은 것만으로 운영 이익을 입증하지 못한다. 공정값 이탈 규칙은 fit 중앙값/IQR에서의 평균 절대 거리이며 현장이 승인한 공정 조치 규칙이 아니다.

이 비교로 현재 복잡한 정책의 추가가치를 확인하지 못했다. 다만 여기서 가장 높았다는 이유로 FIFO를 현장 정책으로 새로 채택하지도 않는다. 모두 이미 본 구간의 설명용 결과다. 고정 시간순 흐름에서의 순서 효과와 검사정답 확보 방식을 새 자료로 확인해야 한다.[J01]

'''
    body=body.replace('## 제3장.',insert+'## 제3장.')
    body=body.replace('### 결측과 미관측 결과','### 결측과 미관측 결과')
    caveat='''추가로, 현재 품질점수는 #42 파일에 실제 존재하는 행에만 연결된다. 같은 가용 행을 단순 기준에도 적용했으므로 이 비교의 내부 분모는 같지만, 그 행 선택이 실제 센서 가용성이나 검사 대상 선정과 독립적인지는 확인되지 않았다. 전체 생산 흐름에 모델 점수를 낼 수 있다는 현장 검증으로 확대하지 않는다. 예열 구간의 품질 정답 부재와 이 선택 문제는 데이터가 더 필요하다는 별개의 제약이다.[L01,J01]

'''
    body=body.replace('## 제4장.',caveat+'## 제4장.')
    body=body.replace('우선 기존 검사 방식과 제안 정책을 같은 도착 흐름에서 기록만 하는 shadow 평가로 비교한다.','먼저 현장의 기존 검사 방식을 확인하고 FIFO·과거빈도 기준과 제안 정책을 같은 도착 흐름에서 기록만 하는 shadow 평가로 비교한다.')
    body=body.replace('새 학습 없이 수치·해시·모델 선택·queue 예산과 분모·저장 모델의 예측을 검사한다.','새 학습 없이 수치·해시·모델 선택·queue 예산과 분모·저장 모델의 예측을 검사한다. 회차6 단순 기준은 별도 검증 명령과 근거 파일을 사용한다.')
    body=body.replace('python build_report.py --check','python build_report.py --check\npython verify_judge_baselines.py')
    body=body.replace('## 부록 근거 목록과 검토 질문','## 부록 근거 목록과 검토 질문')
    body=body.replace('E01 `reports/', 'J01 `reports/submission_round6/baselines_final/baseline_summary.csv`, `baseline_metrics.csv`, `baseline_actions.parquet`, `receipt.json`: 회차6 단순 기준 비교. 과거 개발 자료의 사후 설명이며 운영 채택/독립 검증 아님.\n\nE01 `reports/',1)
    body+='''\n## 경진대회 만족도 조사 완료 페이지 캡쳐 화면

[미완료: 실제 응답자가 만족도 조사를 완료한 뒤 완료 화면을 이 자리에 첨부해야 함]

공식 양식의 필수 항목이며 예시 이미지를 완료 증빙으로 사용하지 않는다. 공식 양식에 기재된 설문 주소는 https://naver.me/FetWt7SN 이다. 응답과 캡처는 아직 수행하지 않았다.
'''
    cover='''# 제6회 K-인공지능 제조데이터 분석 경진대회 보고서

프로젝트명: CastGuard 다이캐스팅 검사 우선순위 비교

팀명: [미완료: 실제 팀명 입력]

중소·중견기업 재직자 부문

## 내용요약

주조 품질보증을 주 데이터, 설비 예지보전을 보조 데이터로 연계해 제한된 검사 용량의 배분을 비교했다. 같은 개발 흐름의 20% 용량에서 FIFO는 {{FIFO_CAP}}%, 품질 Q는 {{Q_CAPTURE}}%, 상태 결합 GQ는 {{GQ_CAPTURE}}%의 양성 Shot을 포착했다. 현재 결합 정책의 우월성과 실제 비용 절감은 입증하지 못했다. 원본 계보·전체 분모·보류 적체·조건부 비용을 검증했고, 물리 키·단위·검사시각 확인을 적용의 선행 조건으로 남겼다. 이미 본 데이터의 회고·개발 분석이다.

상기 본인(팀)은 위의 내용과 같이 제6회 K-인공지능 제조데이터 분석 경진대회 결과 보고서를 제출합니다.

2026년 [미완료]월 [미완료]일

팀장: [미완료: 성명] (서명 미완료)

팀원: [미완료: 성명] (서명 미완료)

팀원: [미완료: 성명] (서명 미완료)

(사)중소기업기술혁신협회 귀중

양식 대응 검토초안: 실제 서명·설문·최종 HWPX 변환·제출 미완료. 장별 배점은 공식 양식의 표기를 보존했으며 과제35/15 대 양식40/10의 충돌을 해결한 것으로 보지 않는다.

'''
    template=cover+body
    content=fill(template,facts)
    used=sorted(set(re.findall(r'\{\{([A-Z0-9_]+)\}\}',template)))
    (out/'CastGuard_form_draft.md').write_text(content,encoding='utf-8')
    (out/'source_template.md').write_text(template,encoding='utf-8')
    evidence={'template_authority':'docs/sources/oct03_round4/employee_report_template_2026.hwpx',
      'template_sha256':sha(root/'docs/sources/oct03_round4/employee_report_template_2026.hwpx'),
      'report_sha256':sha(out/'CastGuard_form_draft.md'),'metrics':{k:facts[k] for k in used},'native_hwpx_created':False,
      'native_editor_or_renderer_confirmed':False,'human_myeongjo_available':False,'blind_rule':'affiliations/company/school/logo and identifying information prohibited; personal/team names permitted',
      'page_limit_confirmed':False,'size_filename_portal_rules_confirmed':False,'rubric_conflict_unresolved':True,
      'fields_missing':['team_name','names','actual_signatures','date','survey_completion_capture'],'new_training':False}
    (out/'report_evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    return content,evidence

if __name__=='__main__':
    text,e=build();print(json.dumps({'metrics':len(e['metrics']),'characters':len(text),'native_hwpx_created':False}))
