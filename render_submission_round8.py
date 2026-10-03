"""Editable HTML and visually verifiable PDF fallback for the unsupported native HWPX."""
from pathlib import Path
from hashlib import sha256
import html,json,re
from reportlab.platypus import SimpleDocTemplate,Paragraph,Table,TableStyle,Spacer,PageBreak
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_CENTER,TA_RIGHT
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'reports/submission_round8'
FONT=Path('C:/Windows/Fonts/batang.ttc');BOLD=Path('C:/Windows/Fonts/malgunbd.ttf')
W,H=595.28,841.86;LEFT=RIGHT=56.69;TOP=BOTTOM=42.52

def parse_blocks(text):
    lines=text.splitlines();blocks=[];i=0
    while i<len(lines):
        s=lines[i].strip()
        if not s:i+=1;continue
        if s.startswith('```'):
            values=[];i+=1
            while i<len(lines) and not lines[i].startswith('```'):values.append(lines[i]);i+=1
            blocks.append(('code','\n'.join(values)));i+=1;continue
        if s.startswith('|'):
            rows=[]
            while i<len(lines) and lines[i].strip().startswith('|'):
                row=[v.strip() for v in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch('[: -]+',v) for v in row):rows.append(row)
                i+=1
            blocks.append(('table',rows));continue
        kind='h3' if s.startswith('### ') else 'h2' if s.startswith('## ') else 'h1' if s.startswith('# ') else 'p'
        value=s[4:] if kind=='h3' else s[3:] if kind=='h2' else s[2:] if kind=='h1' else s
        blocks.append((kind,value.replace('`','')));i+=1
    return blocks

def render():
    pdfmetrics.registerFont(TTFont('FormBody',str(FONT),subfontIndex=0));pdfmetrics.registerFont(TTFont('FormBold',str(BOLD)))
    body=ParagraphStyle('body',fontName='FormBody',fontSize=14,leading=22.4,wordWrap='CJK',spaceAfter=11,allowWidows=0,allowOrphans=0)
    small=ParagraphStyle('small',parent=body,fontSize=10,leading=16,spaceAfter=6)
    sub=ParagraphStyle('sub',parent=body,fontName='FormBold',fontSize=14,leading=22.4,spaceBefore=12,spaceAfter=8,keepWithNext=True)
    chapter=ParagraphStyle('chapter',parent=sub,fontSize=17,leading=25,spaceBefore=0,spaceAfter=16)
    cell=ParagraphStyle('cell',parent=body,fontSize=10.5,leading=16,spaceAfter=0)
    head=ParagraphStyle('head',parent=cell,fontName='FormBold')
    coverbody=ParagraphStyle('coverbody',parent=body,fontSize=12,leading=19.2,spaceAfter=0)
    cent=ParagraphStyle('center',parent=coverbody,alignment=TA_CENTER)
    title=ParagraphStyle('title',parent=cent,fontName='FormBold',fontSize=15,leading=22)
    text=(OUT/'CastGuard_current_review.md').read_text(encoding='utf-8');blocks=parse_blocks(text)
    esc=html.escape
    summary=text.split('## 내용요약\n\n',1)[1].split('\n\n상기 ',1)[0]
    sign='상기 본인(팀)은 위의 내용과 같이 제6회 K-인공지능 제조데이터 분석 경진대회 결과 보고서를 제출합니다.<br/><br/>2026년 [미완료]월 [미완료]일<br/><br/>팀장: [미완료: 성명] (서명 미완료)<br/>팀원: [미완료: 성명] (서명 미완료)<br/>팀원: [미완료: 성명] (서명 미완료)<br/><br/>(사)중소기업기술혁신협회 귀중'
    coverrows=[[Paragraph('제6회 K-인공지능 제조데이터 분석 경진대회 보고서',title),''],
      [Paragraph('프로젝트명',cent),Paragraph('CastGuard 다이캐스팅 검사 우선순위 비교',coverbody)],
      [Paragraph('팀명',cent),Paragraph('[미완료: 실제 팀명 입력]',coverbody)],
      [Paragraph('내용요약',cent),Paragraph(esc(summary),coverbody)],
      [Paragraph(sign,coverbody),'']]
    cover=Table(coverrows,colWidths=[87.06,388.36],rowHeights=[41.56,34.67,34.67,290,230])
    cover.setStyle(TableStyle([('SPAN',(0,0),(1,0)),('SPAN',(0,4),(1,4)),('GRID',(0,0),(-1,-1),.6,colors.black),
     ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#D6D6D6')),('BACKGROUND',(0,1),(0,3),colors.HexColor('#D6D6D6')),
     ('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8)]))
    rubric_note='장별 배점은 양식의 표기를 보존했다. 과제의 모델/오류 35/15와 양식 40/10의 충돌은 미해결이다.'
    story=[Paragraph('중소·중견기업 재직자 부문',ParagraphStyle('track',parent=small,alignment=TA_RIGHT)),Spacer(1,7),cover,Spacer(1,10),Paragraph('검토초안: 실제 서명·설문·최종 HWPX 변환·제출 미완료',small),Paragraph(rubric_note,small)]
    first=next(i for i,(k,v) in enumerate(blocks) if k=='h2' and v.startswith('제1장.'))
    htmlbody=[];appendix=False
    for kind,value in blocks[first:]:
        if kind=='h2':
            story.append(PageBreak());appendix=value.startswith('부록');story.append(Paragraph(esc(value),chapter));htmlbody.append('<h2>'+esc(value)+'</h2>')
        elif kind=='h3':story.append(Paragraph(esc(value),sub));htmlbody.append('<h3>'+esc(value)+'</h3>')
        elif kind=='table':
            n=len(value[0]);available=W-LEFT-RIGHT
            weights=([.31,.2,.49] if n==3 else [.29,.17,.25,.29] if n==4 else [.14,.17,.20,.30,.19] if n==5 else [1/n]*n)
            t=Table([[Paragraph(esc(v),head if i==0 else cell) for v in row] for i,row in enumerate(value)],colWidths=[available*x for x in weights],repeatRows=1)
            t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.5,colors.HexColor('#D9D9D9')),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#EEEEEE')),
             ('VALIGN',(0,0),(-1,-1),'MIDDLE'),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7)]))
            story.extend([Spacer(1,5),t,Spacer(1,14)])
            htmlbody.append('<table>'+''.join('<tr>'+''.join(f'<{"th" if i==0 else "td"}>'+esc(v)+f'</{"th" if i==0 else "td"}>' for v in row)+'</tr>' for i,row in enumerate(value))+'</table>')
        elif kind=='code':story.append(Paragraph('<br/>'.join(esc(x) for x in value.splitlines()),small));htmlbody.append('<pre>'+esc(value)+'</pre>')
        else:story.append(Paragraph(esc(value),small if appendix else body));htmlbody.append('<p>'+esc(value)+'</p>')
    def foot(canvas,doc):
        canvas.saveState();canvas.setFont('FormBody',8);canvas.drawRightString(W-RIGHT,23,str(doc.page));canvas.restoreState()
    pdf=OUT/'CastGuard_current_review.pdf'
    doc=SimpleDocTemplate(str(pdf),pagesize=(W,H),leftMargin=LEFT,rightMargin=RIGHT,topMargin=TOP,bottomMargin=BOTTOM,
     title='다이캐스팅 검사 우선순위 비교',author='',subject='회차8 최신 공식 양식 대응 검토초안')
    doc.build(story,onFirstPage=foot,onLaterPages=foot)
    coverhtml='<section class="cover"><p class="track">중소·중견기업 재직자 부문</p><table><tr><th colspan="2" class="title">제6회 K-인공지능 제조데이터 분석 경진대회 보고서</th></tr><tr><th>프로젝트명</th><td>CastGuard 다이캐스팅 검사 우선순위 비교</td></tr><tr><th>팀명</th><td>[미완료: 실제 팀명 입력]</td></tr><tr><th>내용요약</th><td class="summary">'+esc(summary)+'</td></tr><tr><td colspan="2" class="sign">'+sign+'</td></tr></table><p class="note">검토초안: 실제 서명·설문·최종 HWPX 변환·제출 미완료</p></section>'
    coverhtml=coverhtml.replace('</section>','<p class="note">'+esc(rubric_note)+'</p></section>')
    stylesheet='@page{size:A4;margin:15mm 20mm}body{font-family:"휴먼명조",Batang,serif;font-size:14pt;line-height:1.6;color:#000;background:#fff;max-width:170mm;margin:15mm auto}h2{font-size:17pt;page-break-before:always;margin:0 0 14pt}h3{font-size:14pt;margin:14pt 0 8pt}p{margin:0 0 11pt}table{border-collapse:collapse;width:100%;margin:8pt 0 14pt;font-size:10.5pt}th,td{border:1px solid #d9d9d9;padding:8pt;vertical-align:middle}th{background:#eee;text-align:left}pre,.note{font-size:10pt;white-space:pre-wrap}.track{text-align:right;font-size:10pt}.cover table{font-size:12pt}.cover th,.cover td{border:1px solid #000}.cover th{background:#d6d6d6}.cover th:first-child{width:31mm}.cover .title{font-size:15pt;text-align:center}.summary{height:102mm}.sign{height:81mm}a{color:inherit}'
    page='<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>다이캐스팅 검사 우선순위 비교</title><style>'+stylesheet+'</style></head><body>'+coverhtml+''.join(htmlbody)+'</body></html>'
    (OUT/'CastGuard_current_review.html').write_text(page,encoding='utf-8')
    receipt={'pdf_sha256':sha256(pdf.read_bytes()).hexdigest(),'markdown_sha256':sha256((OUT/'CastGuard_current_review.md').read_bytes()).hexdigest(),
     'html_sha256':sha256((OUT/'CastGuard_current_review.html').read_bytes()).hexdigest(),'page_mm':'A4','margins_pt':[LEFT,RIGHT,TOP,BOTTOM],
     'font_substitution':'Batang body instead of unavailable Human Myeongjo; Malgun Gothic bold headings',
     'body_pt':14,'body_leading_percent':160,'native_hwpx_layout_verified':False,'cover_table_semantics_retained':True,
     'real_survey_or_signature_created':False,'author_metadata_blank':True,'fonts_distributed':False}
    (OUT/'render_receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(str(pdf))

if __name__=='__main__':render()
