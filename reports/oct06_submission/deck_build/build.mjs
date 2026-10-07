import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {Presentation,PresentationFile} from '@oai/artifact-tool';
process.env.RUNTIME_NODE_MODULES='C:/Users/JH/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const root=path.resolve('../../../..',path.relative('../../../..',process.cwd()));
// Run from repository root; package inputs are generated directly from sealed result tables.
const workspace=process.cwd();
const build=path.join(workspace,'reports/oct06_submission/deck_build');
const skill='C:/Users/JH/.codex/plugins/cache/openai-primary-runtime/presentations/26.921.10847/skills/presentations';
const py='C:/Users/JH/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe';
const {finalizePresentation,applyPresentationChartFont}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
const d=JSON.parse(await fs.readFile(path.join(workspace,'reports/oct06_submission/deck_data.json'),'utf8'));
const prs=Presentation.create({slideSize:{width:1280,height:720}});
const font='Malgun Gothic',ink='#172B43',muted='#53657B',blue='#2864DC';
const charts=[],tables=[];
function text(s,value,x,y,w,h,size=28,color=ink,bold=false){
 const z=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h+12},fill:'none',line:{fill:'none',width:0}});
 z.text=value;z.text.style={typeface:font,fontSize:size,color,bold,autoFit:'none'};return z;
}
function slide(title,source,note=''){
 const s=prs.slides.add();s.background.fill='#FFFFFF';
 text(s,title,64,42,1152,92,42,ink,true);
 text(s,`${prs.slides.items.length}  /  CastGuard · 과제②`,64,664,550,26,15,muted);
 text(s,source,620,664,596,32,13,muted);
 s.speakerNotes.textFrame.setText(note+'\n근거: '+source+'\n재사용 데이터의 탐색 평가. 현장 효과·인과·독립 미래 성능으로 해석하지 않습니다.');
 return s;
}
function table(s,headers,rows,y=182,height=370,widths=null){
 const values=[headers,...rows];const t=s.tables.add({rows:values.length,columns:headers.length,left:64,top:y,width:1152,height,values,
  ...(widths?{columnWidths:widths}:{})});
 t.cells.block({row:0,column:0,rowCount:values.length,columnCount:headers.length}).assign({
  fill:'#FFFFFF',textStyle:{typeface:font,fontSize:22,color:ink},margins:{left:10,right:10,top:10,bottom:10}});
 t.cells.block({row:0,column:0,rowCount:1,columnCount:headers.length}).assign({fill:'#E7EFF8',textStyle:{typeface:font,fontSize:22,color:ink,bold:true}});
 t.borders.assign({style:'solid',fill:'#D6E0EB',width:.6});tables.push(prs.slides.items.length);return t;
}
function chart(s,categories,series,{min=0,max=1,format='0.00',y=190,height=365}={}){
 const c=s.charts.add('bar',{position:{left:64,top:y,width:1152,height},categories,series:series.map(z=>({...z,values:z.values.map(v=>Number(v.toFixed(6)))})),
  barOptions:{direction:'column',grouping:'clustered',gapWidth:85},hasLegend:series.length>1,
  legend:{position:'bottom'},xAxis:{textStyle:{fontFamily:font,fontSize:22,color:ink}},
  yAxis:{min,max,numberFormatCode:format,textStyle:{fontSize:18,color:muted},majorGridlines:{fill:'#D6E0EB',width:.5}},
  dataLabels:{showValue:true,position:'outEnd',numberFormatCode:format,textStyle:{fontSize:21,color:ink}},
  chartFill:'#FFFFFF',plotAreaFill:'#FFFFFF'});
 applyPresentationChartFont(c,{fontFamily:font});charts.push(prs.slides.items.length);return c;
}
let s=slide('CastGuard','2026 제6회 K-인공지능 제조데이터 분석 경진대회');
text(s,'근거를 설명하는\n품질검사 의사결정 지원',64,185,1110,180,58,ink,true);
text(s,'RE제조부터시작하는이세계생활\n팀장 정가현 · 팀원 신종훈',64,415,1120,100,27,muted);
text(s,'공정 완료 후 최종검사 전 · 오프라인 연구와 현장 적용 기본설계',64,563,1130,55,26,blue);

s=slide('추가검사 대상을 고르는 품질 문제','보고서 제1장; #42 품질 / #41 설비');
text(s,'대상: 익명 다이캐스팅 기업 시나리오의 제품군 1·2',64,172,1152,60,30,ink,true);
text(s,'한 Shot의 13종·26개 품질 항목 중 하나라도 불량이면 양성\n기존 최종검사는 유지하고 추가검사 용량 20%를 가정',64,255,1152,120,30);
text(s,'공정 완료 관측 → 위험 점수 → 추가검사 검토 → 최종검사',64,438,1152,65,32,blue,true);
text(s,'실제 기업 실증·검사비·수신시각은 확보되지 않았습니다.',64,555,1152,60,25,muted);

s=slide('품질과 설비를 역할에 맞게 연결','data/processed/manifest.json; docs/PREPROCESSING.md');
table(s,['원시데이터','역할','연계 근거와 한계'],[
 ['#42 · 4,617 Shot','주 데이터 / 품질 정답','공정·센서·제품, 1,073 불량 Shot'],
 ['#41 · 5,161 event','보조 / 과거 이력·상태','(run, Shot)와 공정14 대조; 실제시각 미확인'],
 ['#40 · 73,612행','별도 온도 제거실험','다른 공정과 무리한 행 조인 없음']],180,340,[250,310,592]);
text(s,'품질 없는 행을 정상으로 채우지 않고, 단위·주기 미확인을 명시합니다.',64,565,1152,55,26,muted);

s=slide('validation에서 선택하고 결과를 고정','OCT06_RESEARCH_PROTOCOL.md; selection.json');
text(s,'7개 입력 구성 × 5개 모델 × 3 seed × 5 고정 분할',64,175,1152,60,32,blue,true);
table(s,['항목','고정한 기준'],[
 ['같은 구간','train 2,579 / validation 647 / test 1,387'],
 ['미래 구간','forward run 2·3·4·6, 각 fold에서만 후보 선택'],
 ['모델','Logistic · RF · LightGBM · Ordered CatBoost · HGB'],
 ['시점','과거 검사결과가 20개 공정 event 후 도착한다고 가정']],265,275,[270,882]);
text(s,'525회는 탐색량입니다. 기존에 노출된 test를 독립 검증으로 부르지 않습니다.',64,584,1152,45,24,muted);

s=slide('같은 구간 AP는 0.3845까지 개선','summary.csv; n=1,387 / 양성272; 3seed 평균');
const reps=['P','H','S','SH','FB','S_FB','SH_FB'];
chart(s,reps,[{name:'재사용 test AP',values:reps.map(r=>d.test.find(x=>x.representation===r).ap),fill:blue}],{max:.5,format:'0.000'});
text(s,'S: 공정·센서 0.3713 → S_FB: 과거 검사결과 추가 0.3845',64,563,1152,44,29,ink,true);
text(s,'불량률의 2배 목표 0.3922에는 미달 · AUC 0.7378 · 20% 포착 117/272',64,610,1152,36,23,muted);

s=slide('검사 피드백과 설비 이력의 효과를 분리','comparisons.csv; adoption_decisions.json');
table(s,['추가 정보','validation AP 차이','재사용 test AP 차이'],[
 ['#41 이력: H − P','+0.0133','−0.0041'],
 ['#41 이력: SH − S','−0.0150','−0.0465'],
 ['과거 검사: S_FB − S','+0.0918','+0.0132'],
 ['#41 이력: SH_FB − S_FB','−0.0127','−0.0415']],175,340,[542,305,305]);
text(s,'피드백은 #42 과거 정답입니다. #41 융합 성공으로 계산하지 않습니다.',64,552,1152,65,28,ink,true);

s=slide('새로운 미래 구간에서는 성능이 약하다','summary.csv; S_FB forward reused test');
chart(s,d.forward.map(x=>'run '+x.fold),[{name:'AUC',values:d.forward.map(x=>x.auc),fill:'#B57537'}],{min:0,max:1,format:'0.000'});
text(s,'4개 forward validation의 일관성 기준 미통과',64,565,1152,44,31,ink,true);
text(s,'제품·시간·run 효과가 혼재합니다. 미래 현장 적용 성공은 미입증입니다.',64,611,1152,36,24,muted);

s=slide('검사결과가 늦으면 이점이 줄어든다','feedback_sensitivity.csv; frozen S_FB; reused test');
const scenarios=['delay5','delay50','delay100','coverage0.2','no_current_partition_returns'];
table(s,['회신 조건','AP','20% 포착률'],scenarios.map(k=>{const x=d.sensitivity.find(z=>z.scenario===k);return [({'delay5':'5 event 지연','delay50':'50 event 지연','delay100':'100 event 지연','coverage0.2':'관측률20%','no_current_partition_returns':'test 구간 정답 회신 없음'})[k],x.ap.toFixed(4),(x.capture20*100).toFixed(2)+'%'];}),170,355,[632,260,260]);
text(s,'기본 20 event: AP 0.3845 / 포착 43.01% · 결과에 맞춰 지연 가정을 바꾸지 않음',64,566,1152,70,25,muted);

s=slide('한 Shot의 점수를 정확히 설명','demo_output.json; q42_r0_s1000; logistic log-odds');
table(s,['변수','원자료 값','모델 기여'],d.explanation.slice(0,5).map(x=>[x.feature,String(x.input_value),(x.contribution>=0?'+':'')+x.contribution.toFixed(4)]),178,325,[562,260,330]);
text(s,'위험 점수 0.2793 / 기준 0.3134 · 절편 + 기여 합으로 실제 점수 재구성',64,537,1152,48,26,blue,true);
text(s,'기여는 예측의 설명입니다. 물리적 원인이나 설정 변경 효과는 아닙니다.',64,592,1152,45,25,muted);

s=slide('맞힌 사례와 실제 오류를 함께 제시','diagnostic_examples.csv; 사후 진단용 첫 row_id');
table(s,['유형','Shot 식별자','위험 점수','실제 정답'],d.examples.map(x=>[x.error_type,x.row_id,x.probability.toFixed(4),String(x.y_defect)]),180,290,[180,532,220,220]);
text(s,'고정 기준: TP 80 · FP 106 · FN 192 · TN 1,009',64,521,1152,55,31,ink,true);
text(s,'정상 FPR 9.51% · 사후 top-k 20% 검사와 다른 평가입니다.',64,589,1152,45,26,muted);

s=slide('적용범위 밖의 입력은 자동으로 보류','joint_support.csv; pair_interactions.csv; reader_support_audit.csv');
text(s,'1,168 / 1,387건에 사람 검토 경고',64,176,1152,70,43,blue,true);
text(s,'환경값·누적 피드백 수의 학습범위 초과, 입력 부족, 공동지지 부족',64,273,1152,85,29);
text(s,'고정 변수쌍: High_Velocity × Casting_Pressure\ntrain 30행·test 20행 이상 cell만 분석\nS_FB log-odds 상호작용은 수치오차 수준',64,393,1152,154,29);
text(s,'경고행을 성능 분모에서 빼지 않았습니다. 공정 설정값을 추천하지 않습니다.',64,594,1152,46,24,muted);

s=slide('자동 위험 탐지와 담당자 검토 연결','castguard/submission_reader.py; demo.html');
table(s,['입력 / 판독 상태','자동 판단','현장 조치 기본설계'],[
 ['누락·현재/미래라벨·중복','거절 또는 미산출','입력 정합성 확인'],
 ['미학습 제품·지지 부족','적용범위 경고','담당자 검토'],
 ['지원 입력 + 높은 점수','추가검사 검토 요청','기존 최종검사 유지'],
 ['#41 상태 경보','품질·설비 공동 검토','생산중지·폐기는 사람 승인']],178,350,[432,330,390]);
text(s,'모델 점수와 조치 기준은 자동 생성 · 설비 제어 명령은 보내지 않음',64,573,1152,60,28,ink,true);

s=slide('설비 도달의 이득과 품질 포착의 손실','oct03_round7/group_metrics.csv; 기존 동결 causal queue');
table(s,['정책','관측 불량 포착 / 505','상태 에피소드 도달 / 15'],[
 ['FIFO','113 (22.376%)','별도 지표'],['Q · 품질','105.4 (20.871%)','1'],['GQ · 품질+설비','102.2 (20.238%)','8']],188,270,[340,402,410]);
text(s,'공통 기회677 · 전체3,395 · 품질 미관측516 · 보류409 · 종료잔량241',64,506,1152,75,27,ink,true);
text(s,'별도 역사적 비교입니다. 새 S_FB의 정책 성능으로 합치지 않습니다.',64,600,1152,40,24,muted);

s=slide('비용 효과는 실제 단가에 달려 있다','cost_scenarios.csv; 임계값 기준 가상검사; 검사비=1');
table(s,['누락비 / 검사비','S 손실','S_FB 손실','감소율'],[1,5,10].map(k=>{const a=d.cost.find(x=>x.policy==='S'&&x.miss_cost_per_inspection_cost===k).normalized_loss;const b=d.cost.find(x=>x.policy==='reader'&&x.miss_cost_per_inspection_cost===k).normalized_loss;return [String(k),String(a),String(b),((a-b)/a*100).toFixed(2)+'%'];}),187,240,[372,260,260,260]);
text(s,'검사108건 증가 / 미포착43건 감소 → 손익분기 비율 2.51',64,476,1152,68,31,blue,true);
text(s,'완전검사·일정 누락비 가정. 경고 처리비 미포함이며 실제 비용절감이 아닙니다.',64,573,1152,70,25,muted);

s=slide('재현 가능한 제출 패키지','submission/CastGuard_source.zip; README; 검수 명세');
text(s,'원본3종 → 고정 분할 → train 학습 → validation 선택 → 재사용 test',64,179,1152,100,31,ink,true);
text(s,'모델·입력 예제·환경 잠금·test 예측·선정 해시·결과표 포함\n한 명령 판독과 별도 경로의 전체 실험 재현\nPDF·편집 PPTX·설문 원본·ZIP을 최종 검수',64,332,1152,180,30);
text(s,'기존 자료와 사용자 변경을 보존하고, 실제 접수와 파일 완성을 구분합니다.',64,588,1152,55,25,muted);

s=slide('성과와 다음 현장 검증','보고서 제2–5장; reader_uncertainty.json');
text(s,'같은 구간: AUC 0.7378 · AP 0.3845 · 20% 포착 43.01%',64,175,1152,95,34,blue,true);
text(s,'과거 검사결과의 조건부 추가가치를 측정하고\n입력 위험·설명·검사 판단을 실제 도구로 연결했습니다.',64,296,1152,120,31);
text(s,'남은 핵심: 미래 구간 성능 / #41 추가가치 / 수신시각 / 실제 비용\n다음 검증: 미노출 생산구간의 shadow pilot과 전체 분모 평가',64,476,1152,128,28,muted);

await fs.mkdir(build,{recursive:true});
const candidate=path.join(build,'candidate.pptx');
await (await PresentationFile.exportPptx(prs)).save(candidate);
const result=await finalizePresentation({workspaceDir:workspace,candidatePath:candidate,finalPath:path.join(workspace,'submission/CastGuard_presentation.pptx'),
 pythonExecutable:py,integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),
 layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit',...tables.flatMap(n=>['--require-native-table-slide',String(n)])],
 explicitTotalSlideCount:16,requiredNativeTableOwnerSlides:tables,requiredNativeChartOwnerSlides:charts,
 materializeLiteralChartWorkbooks:true,fontPolicy:{basis:'design',families:[font]},verifyArtifactToolImport:true,
 receiptPath:path.join(build,'validation-v2.json')});
await fs.writeFile(path.join(build,'finalizer-result.json'),JSON.stringify(result,null,2));
console.log('finalized',prs.slides.items.length,'slides');
