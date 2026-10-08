"""Keep the existing editable presentation design and add verified team results."""
from pathlib import Path

root=Path(__file__).resolve().parent
text=(root/'reports/oct06_submission/deck_build/build.mjs').read_text(encoding='utf-8')
text=text.replace('reports/oct06_submission/deck_build','reports/oct08_submission/deck_build')
text=text.replace('26.921.10847','26.1007.11041')
text=text.replace("const prs=Presentation.create", "const n=JSON.parse(await fs.readFile(path.join(workspace,'reports/oct08_submission/new_deck_data.json'),'utf8'));\nconst prs=Presentation.create")
text=text.replace("submission/CastGuard_presentation.pptx'", "reports/oct08_submission/candidate/CastGuard_presentation.pptx'")
text=text.replace('explicitTotalSlideCount:16','explicitTotalSlideCount:19')
start=text.index("s=slide('품질과 설비를 역할에 맞게 연결'")
end=text.index("s=slide('validation에서 선택하고 결과를 고정'",start)
text=text[:start]+r'''s=slide('세 데이터의 역할과 연결 단계','보고서 1.2·2.3절; 고정 분할 · train 분위 정렬');
text(s,'#42  품질·공정·센서',64,176,1152,55,36,blue,true);
text(s,'현재 관측  +  도착한 과거 검사 회신  →  품질 위험과 개별 설명',64,245,1152,65,29);
text(s,'#41  설비 이력·상태',64,355,1152,50,32,ink,true);
text(s,'과거 이력 → 품질 입력 비교     상태 Gate → 품질·설비 담당자 검토',64,415,1152,60,28);
text(s,'#40  다른 공정의 주조 데이터',64,512,1152,50,32,ink,true);
text(s,'train 분위 정렬 → 전이 점수 비교     온도 제거 → 수집 후보 제안',64,573,1152,55,27,muted);

'''+text[end:]
pos=text.index("s=slide('새로운 미래 구간에서는 성능이 약하다'")
text=text[:pos]+r'''s=slide('네 가지 데이터 조합을 같은 모델로 비교','oct08_fusion/summary.csv; RF · 3 seed 평균');
const combo=[['S','#42'],['SH','#42 + #41'],['S_T','#42 + #40'],['SH_T','#42 + #41 + #40']];
function fusion(rep,role,model='random_forest'){return n.fusion.find(x=>x.scheme==='within_run'&&x.representation===rep&&x.role===role&&x.model===model);}
table(s,['조합','val AP','test AP','test AUC','20% 포착'],combo.map(([rep,label])=>{const v=fusion(rep,'validation'),t=fusion(rep,'test');return [label,v.ap.toFixed(4),t.ap.toFixed(4),t.auc.toFixed(4),(t.capture20*100).toFixed(2)+'%'];}),176,290,[360,198,198,198,198]);
text(s,'모두 같은 1,387건 / 불량 272건 / 검사 277건',64,493,1152,46,29,blue,true);
text(s,'#40 전이의 validation AP +0.0038: 사전 기준 +0.02 미달\n피드백 포함 네 조합과 로지스틱에서도 추가 입력 채택 기준 미달',64,552,1152,82,25,muted);

'''+text[pos:]
pos=text.index("s=slide('적용범위 밖의 입력은 자동으로 보류'")
text=text[:pos]+r'''s=slide('불량 유형별 순위 성능과 양성 수','팀 add 고정 모델 재현; 5 seed · 같은 구간 test');
table(s,['유형','양성 / 1,387','AUC','AP','불량률'],n.types.map(x=>[x.target,String(x.test_positive),x.test_auc.toFixed(4),x.test_ap.toFixed(4),(x.prevalence*100).toFixed(2)+'%']),175,320,[352,220,180,180,220]);
text(s,'Etc는 주요 4종 이외의 합집합 · 유형 중복을 허용',64,522,1152,42,27,blue,true);
text(s,'A_FB: 품질 행 순번·지연 회신을 쓰는 별도 보조 모델\n현재 판독기의 자동 유형 진단이나 미래 성능을 뜻하지 않음',64,575,1152,74,24,muted);

'''+text[pos:]
pos=text.index("s=slide('비용 효과는 실제 단가에 달려 있다'")
text=text[:pos]+r'''s=slide('적응형 설비 경보와 정상 경보 부담','팀 add Gate 재현; 5 seed · 지연 정상 회신 가정');
const gates=n.gate.filter(x=>x.policy==='적응형'&&x.scheme!=='run_holdout');
table(s,['구간','탐지 / 관측 / 전체','정상 행','정상 FPR'],gates.map(x=>[x.scheme==='within_run'?'같은 구간':'미래 run '+x.fold,`${x.detected_within_k} / ${x.episodes} / ${x.all_episodes_in_test_boundaries}`,String(x.normal_rows),(x.false_stop_rate*100).toFixed(2)+'%']),173,330,[300,392,220,240]);
text(s,'같은 구간: 고정 2.68% → 적응형 2.29% · 탐지 8개 유지',64,525,1152,52,28,blue,true);
text(s,'원래 FPR 2% 목표에는 미달 · 미래 run 3은 0/3\n실제 생산중지 성과가 아니며, 기존 JH Gate와 평가 모집단이 다름',64,580,1152,67,23,muted);

'''+text[pos:]
text=text.replace("text(s,'남은 핵심: 미래 구간 성능 / #41 추가가치 / 수신시각 / 실제 비용\\n다음 검증: 미노출 생산구간 shadow pilot과 전체 분모 평가'", "text(s,'네 조합 비교 + 팀 Gate·유형별 재현을 통합했습니다.\\n다음 검증: 미노출 생산 구간 / 수신 시각 / 실제 비용'")
text=text.replace("text(s,'같은 구간: AUC 0.7378 · AP 0.3845 · 20% 포착 43.01%'", "text(s,'추가 검사 약 20%로 불량 43.01% 포착'")
text=text.replace("text(s,'과거 검사결과의 조건부 추가가치를 측정하고\\n입력 위험·설명·검사 판단을 실제 도구로 연결했습니다.'", "text(s,'같은 구간 재사용 test · 117/272건 · 무작위 기대값의 2.15배\\nAUC 0.7378 / AP 0.3845 · 기존 판독 모델 유지'")
text=text.replace('검사결과','검사 결과').replace('원본3종','원본 3종').replace('품질미관측','품질 미관측')
text=text.replace('기존 자료와 사용자 변경을 보존하고, 실제 접수와 파일 완성을 구분합니다.',
                  '네 조합·팀 보조 모델의 재현 코드와 행별 예측을 함께 제공합니다.')
(root/'reports/oct08_submission/deck_build/build.mjs').write_text(text,encoding='utf-8')
print('prepared 19-slide editable deck')
