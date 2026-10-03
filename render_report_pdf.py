"""Render the evidence-bound six-chapter review draft. Requires reportlab and a Korean TTF."""
from pathlib import Path
import argparse,json,re,hashlib
from xml.sax.saxutils import escape
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak,Preformatted
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT,TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

ROOT=Path(__file__).resolve().parent
def render(root,font,boldfont):
    out=root/'reports/submission_draft'; text=(out/'CastGuard_report_draft.md').read_text(encoding='utf-8')
    if not font.exists() or not boldfont.exists(): raise FileNotFoundError('Provide --font and --bold-font with available Korean TrueType files')
    pdfmetrics.registerFont(TTFont('ReportKR',str(font)));pdfmetrics.registerFont(TTFont('ReportKRB',str(boldfont)))
    pdfmetrics.registerFontFamily('ReportKR',normal='ReportKR',bold='ReportKRB')
    body=ParagraphStyle('Body',fontName='ReportKR',fontSize=14,leading=22.4,wordWrap='CJK',spaceAfter=10,textColor=colors.black,allowWidows=0,allowOrphans=0)
    small=ParagraphStyle('Small',parent=body,fontSize=10.5,leading=16,spaceAfter=8)
    h1=ParagraphStyle('Title',parent=body,fontName='ReportKRB',fontSize=22,leading=31,spaceAfter=20,keepWithNext=True)
    h2=ParagraphStyle('Chapter',parent=body,fontName='ReportKRB',fontSize=18,leading=27,spaceBefore=4,spaceAfter=18,keepWithNext=True)
    h3=ParagraphStyle('Section',parent=body,fontName='ReportKRB',fontSize=14,leading=23,spaceBefore=14,spaceAfter=8,keepWithNext=True)
    cellstyle=ParagraphStyle('Cell',parent=body,fontSize=10.5,leading=15,spaceAfter=0)
    headstyle=ParagraphStyle('HeadCell',parent=cellstyle,fontName='ReportKRB')
    code=ParagraphStyle('Command',parent=small,fontSize=10,leading=15,wordWrap='CJK',spaceBefore=6,spaceAfter=12)
    story=[]; lines=text.splitlines(); i=0; appendix=False
    while i<len(lines):
        s=lines[i].strip()
        if not s: i+=1;continue
        if s.startswith('```'):
            parts=[];i+=1
            while i<len(lines) and not lines[i].startswith('```'): parts.append(lines[i]);i+=1
            story.append(Paragraph('<br/>'.join(escape(x) for x in parts),code));i+=1;continue
        if s.startswith('|'):
            rows=[]
            while i<len(lines) and lines[i].strip().startswith('|'):
                row=[x.strip() for x in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch('[: -]+',x) for x in row): rows.append(row)
                i+=1
            n=len(rows[0]); available=A4[0]-104
            widths={3:[available*.31,available*.20,available*.49],4:[available*.28,available*.18,available*.27,available*.27],5:[available*.14,available*.17,available*.21,available*.29,available*.19]}.get(n,[available/n]*n)
            cells=[[Paragraph(escape(x),headstyle if r==0 else cellstyle) for x in row] for r,row in enumerate(rows)]
            t=Table(cells,colWidths=widths,repeatRows=1,hAlign='LEFT')
            t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.5,colors.HexColor('#D9D9D9')),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#E8EDF3')),
                ('VALIGN',(0,0),(-1,-1),'MIDDLE'),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8),
                ('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8)]))
            story.extend([Spacer(1,4),t,Spacer(1,13)]);continue
        if s.startswith('### '): story.append(Paragraph(escape(s[4:]),h3))
        elif s.startswith('## '):
            title=s[3:]
            if title.startswith(('제','부록','내용요약')): story.append(PageBreak())
            appendix=title.startswith('부록');story.append(Paragraph(escape(title),h2))
        elif s.startswith('# '): story.append(Paragraph(escape(s[2:]).replace('와 설비','와<br/>설비'),h1))
        else:
            content=escape(s).replace('`','')
            if s.startswith('2026 제6회 '): content=content.replace(' 중소','<br/>중소')
            story.append(Paragraph(content,small if appendix else body))
        i+=1
    dest=out/'CastGuard_report_draft.pdf'
    def footer(canvas,doc):
        canvas.saveState();canvas.setFont('ReportKR',8.5);canvas.setFillColor(colors.HexColor('#555555'))
        canvas.drawString(52,31,'CastGuard 검토초안  |  2026-10-03');canvas.drawRightString(A4[0]-52,31,str(doc.page));canvas.restoreState()
    doc=SimpleDocTemplate(str(dest),pagesize=A4,rightMargin=52,leftMargin=52,topMargin=48,bottomMargin=52,
      title='다이캐스팅 검사 우선순위와 설비 상태 연계 검증',author='',subject='2026 제6회 재직자 공통 6장 보고서 검토초안')
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    receipt={'markdown_sha256':hashlib.sha256((out/'CastGuard_report_draft.md').read_bytes()).hexdigest(),
       'pdf_sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'font':font.name,'font_sha256':hashlib.sha256(font.read_bytes()).hexdigest(),
       'style':'A4, 14pt Korean body, 160% leading, 6 common chapters; review typography, not exact native HWPX layout',
       'author_metadata_blank':True,'official_template_unchanged':True}
    (out/'render_receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(str(dest))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--font',type=Path,default=Path('C:/Windows/Fonts/malgun.ttf'));p.add_argument('--bold-font',type=Path,default=Path('C:/Windows/Fonts/malgunbd.ttf'));a=p.parse_args();render(ROOT,a.font,a.bold_font)
