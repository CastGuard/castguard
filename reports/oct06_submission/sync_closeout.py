from pathlib import Path
from datetime import datetime,timezone,timedelta
import json,hashlib,re

R=Path(__file__).resolve().parents[2]
now=datetime.now(timezone(timedelta(hours=9)))
stamp=now.strftime('%Y-%m-%d %H:%M KST')
deadline=datetime(2026,10,8,23,59,tzinfo=now.tzinfo)
handoff=datetime(2026,10,7,18,tzinfo=now.tzinfo)
def write(path,text):(R/path).write_text(text,encoding='utf-8')
def prepend(path,text):
    p=R/path;old=p.read_text(encoding='utf-8');first,rest=old.split('\n',1)
    p.write_text(first+'\n\n'+text+'\n\n'+rest.lstrip(),encoding='utf-8')

summary=f'''## 10/6 등록 연구·제출 후보 검수 완료 · {stamp}

최신 기준은 [실행 계획](EXECUTION_PLAN_2026-10-06.md), [등록 실험](OCT06_RESEARCH_PROTOCOL.md), [제출 묶음](../submission/README.md)이다. 아래 10/5 및 이전 동결·미완료 기록은 당시 판단이며 현재 상태를 대신하지 않는다. JH의 기존 변경·원본·분할·10/2 결과를 보존했다. `add`에서는 검사 피드백 민감도·규제 모델·조건별 분석을 참고하고 공정 event 기준으로 재구현했다.

| 항목 | 이번 근거와 판정 |
|---|---|
| 개발 선택 | 7입력×5모델×3seed×5분할=525 fit 완료. validation 선택35개 그룹을 봉인한 뒤 재사용 test 평가 |
| 같은 구간 | S_FB logistic, AUC0.7378/AP0.3845, 사후20% 순위검사117/272(43.01%). S 대비 AP+0.0132, 포착+3건 |
| 원래 목표 | AP 최소0.3922 미달. AUC 최소0.70 충족·상향0.75 미달. 기존 목표를 소급 수정하지 않음 |
| 불확실성·미래 | 6run 재표본 AP차95% 범위[-0.0365,0.0913]. 미래4구간 AUC0.357/0.432/0.566/0.513; validation 일관성 실패 |
| 다종 데이터 | #42 주 품질 + #41 과거 이력/상태 연계와 제거실험. #41 품질 추가가치 채택실패 유지. #40 온도제거는 별도 보조근거 |
| 자동 판독 | 현재 관측과 도착한 과거 회신→위험·개별 기여·범위 경고·사람검토. 입력 계약은 [별도 안내](SUBMISSION_READER.md). 자동 설비 제어 없음 |
| 부담과 KPI | validation 임계값에서 TP80/FP106/FN192/TN1009, 정상FPR9.51%. 지원경고1168/1387. 비용표는 가정 시나리오이고 실측 개선 아님 |
| 제출 후보 | 보고서14쪽, 발표16장 PDF/PPTX, 소스 ZIP184파일, 설문 원본, 판독 HTML, 명세·해시 |
| 검증 | 전체413검사 통과. 최종 ZIP 새15검사·CLI11건 통과. 별도 ZIP 전체재학습210그룹 최대차0; 수치/지연회신/해시 독립 대조 통과 |

보고서14쪽·발표16장 시각 검수, PowerPoint 텍스트 넘침0, 설문 PNG 바이트와 PDF 삽입 픽셀 일치를 확인했다. HTML은 내용·CLI만 검증했고 브라우저 보안 정책의 로컬 URL 차단으로 화면 조작 검수는 미완료다. [최종 검수 근거](../reports/oct06_submission/final_checks.json).

유지할 주장: 조건부 과거 검사 피드백의 관측상 이득, 설명 가능한 연구 판독, 명시적 실패/검토 흐름, 재현 가능한 제출 근거. 버릴 주장: 신규독립 성능, 성공적 #41 품질융합, 인과 공정 최적화, 실제 불량·비용 감소, 수상 보장. 20 event 지연을 유리한5 event로 바꾸지 않았다.

다음 상위3개: ①10/7 12시까지 팀이 표지·서명란과 현장 미확인 가정을 검토, ②10/7 15시까지 참가팀 브라우저에서 HTML 표시 및 발표 리허설, ③10/7 18시 목표로 실제 서명본/포털 제출을 참가팀이 진행하고 접수 증빙 보관(공식10/8 23:59). 외부 확인자료가 없으면 현장효과는 미측정으로 유지한다. 실험은 등록후보 완료로 종료하고 새 데이터 없는 추가 튜닝은 우선하지 않는다. 예약 자동화·새 채팅·푸시·실제 접수는 수행하지 않았다.
'''
for name in ['STRATEGY.md','ROADMAP.md','EXPERIMENTS_NEXT.md']:
    p=R/'docs'/name;s=p.read_text(encoding='utf-8')
    start=s.index('## 10/6 사용자 지시에 따른 실험 재개·제출 완성 작업')
    end=s.index('\n## ',start+4)
    p.write_text(s[:start]+summary+'\n'+s[end:],encoding='utf-8')

rootnote=f'''## 제출 후보 완성 · {stamp}

[submission 안내](submission/README.md)에서 보고서14쪽·발표16장·소스ZIP·설문 원본·판독 화면을 확인합니다. 팀명 **RE제조부터시작하는이세계생활**, 팀장 **정가현**, 팀원 **신종훈**을 반영했습니다.

`add`의 피드백 지연/관측률 분석을 공정 event 기준으로 도입했습니다. 같은 구간 재사용 test에서 과거 검사결과 추가 전후 AP0.3713→0.3845, AUC0.7378, 20% 순위검사117/272입니다. 미래 구간 일관성 및 #41 추가가치 채택에는 실패했습니다. 이전 실험은 보존하고 새 결과는 `reports/oct06_research`에 분리했습니다. test는 독립 검증이 아닙니다.

현재 관측·과거 회신으로 위험·설명·지원경고·사람검토를 자동 산출하는 [새 입력 계약](docs/SUBMISSION_READER.md)을 연결했습니다. 실제 생산중지/설정 변경은 없고 기존 검사를 면제하지 않습니다. 전체413개 검사, 최종 ZIP15개 검사와11건 추론, 별도 ZIP 전체 학습210개 결과 일치를 확인했습니다. [최종 검수](reports/oct06_submission/final_checks.json).

실제 서명과 포털 접수는 참가팀 단계입니다. HTML 브라우저 조작은 도구의 로컬 URL 보안 차단으로 미검수입니다. 아래는 과거 회차별 결과입니다.
'''
for p in ['README.md','CURRENT_REVIEW.md']:prepend(p,rootnote)
prepend('docs/DAILY_REVIEW.md',f'''## 현재 종료 기준 · {stamp}

사용자의10/6 실험 재개 지시에 따라 [10/6–7 계획](EXECUTION_PLAN_2026-10-06.md)이 이전 동결 시각을 갱신했다. 등록 연구와 제출 후보 검수를 완료했으며 다음은 팀 서명/브라우저 확인/접수다. 실제 성능·부분 근거·미측정 구분과 아래 일지 절차는 유지한다. 예약 자동 실행은 없다.''')
prepend('docs/SUBMISSION.md',f'''## 검수된 제출 후보 · {stamp}

최신 파일은 [submission/README](../submission/README.md)와 [검수 명세](../submission/VERIFICATION.json)를 따른다. 보고서 PDF14쪽(팀 정보·6장·서명란·설문 원본), 소스 ZIP184파일(환경·원본3종·전처리/분할·코드·모델·예측·README), 발표 PDF/PPTX16장, 설문 PNG와 데모 HTML을 완성했다. 편집본은 실제 `.pptx`다.

팀명 RE제조부터시작하는이세계생활 / 팀장 정가현 / 팀원 신종훈. 설문 완료 이미지는 제공 원본 바이트 그대로이며 PDF에도 픽셀 일치로 삽입됐다. 최종 ZIP의15개 검사·11개 추론과 모든 PDF/슬라이드 시각 검수를 통과했다. HTML 화면 조작은 브라우저 보안 정책의 로컬 URL 차단으로 미완료다. 실제 서명과 포털 접수·접수 증빙은 남았다. 아래 표는 이전 초안 상태를 보존한 기록이다.''')

p=R/'docs/EXECUTION_PLAN_2026-10-06.md'
p.write_text(p.read_text(encoding='utf-8')+f'''\n## 실행 결과 · {stamp}

모든 등록후보 학습·민감도·오류/공동지지·자동 판독·보고서/발표/ZIP 검수를 계획 시각보다 일찍 마쳤다. 525 fit은 탐색량이며 성능 근거는 별도 지표로 평가한다. 향후 구간 일관성·#41 추가가치 미달을 유지한다. 제출물은 `submission`에 있고 최종 검수는 `reports/oct06_submission/final_checks.json`이다. 전체413개 회귀 통과, 새 ZIP15개 회귀와11건 추론, 별도 재학습210그룹 수치 일치.

팀의 서명·브라우저 표시 확인·리허설·접수 일정은 남겨둔다. 현재까지 실제 접수는 없다. 추가 정보 없는 모델 탐색보다 수신시각/단위/비용과 새 생산구간 확보가 다음 성능 개선 조건이다. 브라우저 화면 검수는 로컬 URL 보안 차단으로 미완료이며 우회하지 않았다.
''',encoding='utf-8')

p=R/'docs/가이드북.html';s=p.read_text(encoding='utf-8');a=s.index('<section>');b=s.index('</section>',a)+len('</section>')
s=s[:a]+f'''<section><h2>10/6 제출 후보 검수 완료</h2><p>{stamp} · RE제조부터시작하는이세계생활 / 정가현·신종훈</p><p>같은 구간 AP 0.3713→0.3845, AUC 0.7378. 미래 구간 일관성·설비 이력 추가가치는 실패를 유지합니다. 위험·개별 설명·범위 경고·담당자 검토를 자동 연결했습니다.</p><p><a href="../submission/README.md">최종 제출 묶음 안내</a> · <a href="../submission/CastGuard_report.pdf">보고서14쪽</a> · <a href="../submission/CastGuard_presentation.pdf">발표PDF16장</a> · <a href="../submission/CastGuard_presentation.pptx">편집PPTX</a> · <a href="../submission/CastGuard_source.zip">소스ZIP</a> · <a href="../submission/CastGuard_demo.html">연구 판독 화면</a></p><p>전체413검사·ZIP재학습210그룹 수치 일치, PDF/발표 시각 검수 완료. HTML 브라우저 조작 미검수(로컬URL 보안 차단), 실제 서명과 포털 접수는 참가팀이 수행합니다.</p><p><a href="EXECUTION_PLAN_2026-10-06.md">실행 계획</a> · <a href="OCT06_RESEARCH_PROTOCOL.md">등록 실험</a> · <a href="SUBMISSION_READER.md">입력 계약</a></p><p><strong>이 아래는 이전 안내 기록입니다.</strong></p></section>'''+s[b:]
p.write_text(s,encoding='utf-8')

daily=R/f'docs/daily/{now:%Y-%m-%d}.md'
text=daily.read_text(encoding='utf-8') if daily.exists() else f'# {now:%Y-%m-%d} 작업 평가 (KST)\n'
roundnum=text.count('## 회차 ')+1
text+=f'''\n## 회차 {roundnum} · 등록 연구·제출 검수 종료 {now:%H:%M}

- 작업 범위/브랜치: JH, add 유용 방법 도입·연구·판독·제출 후보. 기존 변경7개 백업과 원본/프로토콜12해시 보존.
- 기준 {now.isoformat()}: 공식 마감까지 {deadline-now}, 내부 전달 목표까지 {handoff-now}.
- 근거: reports/oct06_research/selection.json, selected_metrics.csv, adoption_decisions.json, independent_verification.json; reports/oct06_submission/final_checks.json, reproduction_check.json.

| 목표 | 이전 | 이번 | 판정·한계 |
|---|---|---|---|
| same-run 품질 | 기존A AP0.2614/AUC0.6274 | 새S_FB AP0.3845/AUC0.7378; 적절한 새S대비 AP+0.0132 | 일부 근거; 입력/모델이 바뀌어 전체 차이를 피드백 효과로 귀속하지 않음 |
| 최소AP·미래 일관성 | 미달 | AP0.3922 미달; 미래4fold 일관성 실패 | 실패 유지; 불리한 결과 포함 |
| 보조#41 추가가치 | 실패 | H−P validation+0.0133<+0.02, SH/SH_FB 음의차 | 실패 유지; #42 피드백을 다종융합으로 주장하지 않음 |
| 자동 판단 | 기존 관측A0 경로 | 새 관측·과거회신·설명·경고·사람검토 | 기능 완료; 지원경고1168/1387, 실제 제어/비용효과 미측정 |
| 제출 후보 | 이전 초안 | 보고서14p·발표16장·ZIP184파일·원본설문·HTML·검수명세 | 파일 완성; 실제 서명/접수 미완료 |
| 재현·검수 | 역사검증398개 | 전체413 통과, 최종 ZIP15통과/11추론, 별도525fit 재생210그룹 최대차0 | 계산 재현 완료; 독립 성능 검증 아님 |

### 평가와 개선

- 채택: 규제 후보 비교, 공정 event 기반 과거 피드백, 지연/관측률 민감도, 조건·오류·공동지지, 자동 사람검토. S_FB/logistic/seed17은 validation만으로 선택했다.
- 버릴 주장: 성공적 다종 품질융합·미래 일반화·인과 최적조건·실제 절감·수상보장. 유지: 같은 구간 조건부 관측이득과 실패근거. 실제 수신시각·단위·비용/원천 적격성은 미측정.
- 분모: 같은 구간 test1387/불량272, 고정 임계FP106/정상1115; 사후20%는277검사/117포착. 기존queue3395/관측2879/불량505와 분리. AP차 재표본구간[-.0365,.0913]은0포함.
- 원본·분할을 유지하고 validation 봉인 뒤 노출 test를 재사용했다. 유리한5event로 기본20event를 바꾸지 않았다. 실험 횟수·회귀 수를 성능으로 쓰지 않는다.
- ZIP에서 report 생성에 필요한 demo.html 누락을 발견해 포함하고 입력 계약/전처리 설명을 보강했다. 최종 ZIP 과학 코드/데이터/모델의 이전 전체재현본 대비 해시 일치를 확인했다.
- 보고서 모든14쪽/발표16장 검수·텍스트 넘침0·설문 원본 바이트/삽입 픽셀 일치. 브라우저 도구가 로컬 파일 열기를 보안 정책으로 거절해 HTML 조작 검수는 미완료로 기록하고 우회하지 않았다.
- 전략·계획·후속실험·제출안내·README·현재 HTML을 이번 실측 상태로 맞췄다. 등록후보 완료로 추가 탐색 종료. 예약 자동화·새 채팅·제출·푸시 없음.

### 다음 상위 3개 작업

1. 참가팀 표지/서명란·현장 가정 확인,10/7 12:00. 확인되지 않은 단위/시각/비용은 가정 유지.
2. 참가팀 브라우저 HTML 확인·발표 리허설,10/7 15:00. 화면 확인이 안 되면 검증된 PDF와 실행 결과로 설명하고 브라우저 검수를 완료 처리하지 않음.
3. 실제 서명·최종 포털 제출 및 증빙 보관,10/7 18:00 목표/공식10/8 23:59. 사용자 지시 없이 외부 접수하지 않음.
'''
daily.write_text(text,encoding='utf-8')

readme=f'''# CastGuard 제출 후보

검수 시각: {stamp}. 팀명 **RE제조부터시작하는이세계생활** · 팀장 **정가현** · 팀원 **신종훈**.

| 파일 | 내용 |
|---|---|
| [CastGuard_report.pdf](CastGuard_report.pdf) | 14쪽: 공식6장 구조·팀 정보·근거/한계·실제 서명란·설문 원본 |
| [CastGuard_source.zip](CastGuard_source.zip) | 원본3종·전처리/고정 분할·코드·잠금 환경·모델·test예측·README·입력 계약,184파일 |
| [CastGuard_presentation.pdf](CastGuard_presentation.pdf) | 발표용16장 PDF |
| [CastGuard_presentation.pptx](CastGuard_presentation.pptx) | 편집 가능한16장 PowerPoint, 실제PPTX 형식 |
| [설문조사완료.png](설문조사완료.png) | 제공 원본 바이트 그대로. 보고서에도 삽입 |
| [CastGuard_demo.html](CastGuard_demo.html) | 실제 연구 판독11건·설명·경고·담당자 검토와 기존정책 비교 |
| [VERIFICATION.json](VERIFICATION.json) | 계산/페이지/파일 검수 근거와 미확인 범위 |
| [CHECKSUMS.sha256](CHECKSUMS.sha256) | 이 묶음의 SHA-256 해시(CHECKSUMS 자신 제외) |

## 결과와 해석

주#42 품질·보조#41 공정/설비의 연계·제거실험을 수행하고 #40 온도제거를 별도 보조분석으로 제시했다. add의 유용한 과거검사 피드백·민감도 방식을 공정event 기준으로 다시 구현했다.

같은 구간 재사용 test에서 S대비 S_FB AP0.3713→0.3845, AUC0.7378, 사후20%검사117/272(43.01%)다. validation 고정 임계값의 결과는 TP80/FP106/FN192/TN1009이며 사후top-k와 다르다. 기본20event 회신지연을 유지했다. 미래 구간 일관성과 #41 품질 추가가치 채택에는 실패했고 AP차 재표본 범위는0을 포함한다. 실제 불량률·폐기비 절감이나 독립 검증 성과로 읽지 않는다.

판독은 현재 관측·과거회신으로 위험과 개별 기여를 계산하고 입력/지원범위 문제를 사람검토로 분류한다. 실제 제어 명령은 없고 기존 검사를 대체하지 않는다. 전체test1387행 중1168행에서지원경고가 발생했으며 분모에서 제외하지 않았다.

## 완료한 확인

- 전체 회귀413개 통과(실패·제외0). 최종 ZIP 별도 폴더의 새 회귀15개와11건 CLI 추론 통과.
- 별도 ZIP의 전체525fit 재학습 결과210그룹, 원본 대비 지표 최대차0. 최종 ZIP의 과학 코드·설정·데이터·모델 해시는 그 재현본과 동일하다. 계산 재현은 새 독립 검증이 아니다.
- 독립 수식 대조210그룹·피드백518표본·보존해시12개 확인. 최종 ZIP183개 파일해시·CRC 확인.
- 보고서14쪽·발표16장 모두 시각 검수, 실제 PowerPoint 텍스트 넘침0. 설문 PNG 바이트·PDF 삽입 픽셀 원본 일치.
- HTML 내용·설명패널11개·외부자원 없는 정적파일 확인. **브라우저 조작 검수는 도구 보안 정책의 로컬URL 차단으로 미완료**다.

## 실제 제출 전 참가팀 단계

보고서13쪽의 두 사람 서명을 실제로 완료하고 최종 서명본을 확인한다. 서명 후 PDF가 바뀌면 현재 해시는 더 이상 일치하지 않으므로 서명본의 SHA-256을 별도로 기록한다. 팀 PC에서 HTML 표시와 발표 리허설을 확인한다. 실제 포털 제출과 접수 증빙 보관은 아직 하지 않았다.

내부 전달/접수 목표10/7 18:00 KST, 보존 공고 원문 기준 공식마감10/8 23:59 KST. 상위 폴더의 실험 로그·렌더 이미지·이전 초안은 제출 파일이 아니다. 제출 ZIP 안 README의 명령으로 판독과 학습을 재현한다. 새 점수가 없는 문서·검수 개선을 모델 성능 개선으로 세지 않는다.
'''
write('submission/README.md',readme)

for path in ['submission/VERIFICATION.json','reports/oct06_submission/final_checks.json']:
    p=R/path;x=json.loads(p.read_text(encoding='utf-8'))
    x['final_zip_smoke']={'tests_passed':15,'tests_failed':0,'cli_records':11,'exit_codes':[0,0]}
    p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
hashes=[]
for p in sorted((R/'submission').iterdir()):
    if p.is_file() and p.name!='CHECKSUMS.sha256':hashes.append(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name)
write('submission/CHECKSUMS.sha256','\n'.join(hashes)+'\n')
print(stamp,'synchronized',len(hashes),'checksums')
