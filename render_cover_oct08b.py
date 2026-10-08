"""Render the 10/8 report with the official template's cover layout.

Page 1 follows the HWPX form: title, a table with 프로젝트명 / 팀명 / 부문 / 내용요약,
the submission declaration, date, signature lines and the addressee. The body
(제1장~부록) is rendered exactly as before; the old trailing signature lines
are dropped because the cover now carries them.
"""
from pathlib import Path
import html
import re
import shutil

from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, PageBreak
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from pypdf import PdfReader, PdfWriter

import build_oct06_submission as old

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / 'reports/oct08b_submission'
OUT = BUILD / 'candidate'
MD = BUILD / 'CastGuard_report.md'
TEAM = old.TEAM


def render(text):
    pdfmetrics.registerFont(TTFont('Body', 'C:/Windows/Fonts/batang.ttc', subfontIndex=0))
    pdfmetrics.registerFont(TTFont('Bold', 'C:/Windows/Fonts/malgunbd.ttf'))
    S = {
        'p': ParagraphStyle('p', fontName='Body', fontSize=14, leading=22.4, wordWrap='CJK', spaceAfter=11),
        'h2': ParagraphStyle('h2', fontName='Bold', fontSize=18, leading=27, wordWrap='CJK', spaceAfter=17, keepWithNext=True),
        'h3': ParagraphStyle('h3', fontName='Bold', fontSize=14, leading=22.4, wordWrap='CJK', spaceBefore=13, spaceAfter=9, keepWithNext=True),
        'cell': ParagraphStyle('cell', fontName='Body', fontSize=10.4, leading=16.5, wordWrap='CJK'),
        'label': ParagraphStyle('label', fontName='Bold', fontSize=11, leading=17, wordWrap='CJK', alignment=1),
        'value': ParagraphStyle('value', fontName='Body', fontSize=11, leading=17, wordWrap='CJK'),
        'summary': ParagraphStyle('summary', fontName='Body', fontSize=10, leading=15.5, wordWrap='CJK'),
        'title': ParagraphStyle('title', fontName='Bold', fontSize=20, leading=30, wordWrap='CJK', alignment=1, spaceAfter=20),
        'center': ParagraphStyle('center', fontName='Body', fontSize=12, leading=19, wordWrap='CJK', alignment=1),
        'right': ParagraphStyle('right', fontName='Body', fontSize=12, leading=19, wordWrap='CJK', alignment=2),
        'sig': ParagraphStyle('sig', fontName='Body', fontSize=12, leading=22, wordWrap='CJK', alignment=2),
    }
    e = html.escape
    summary = text.split('## 내용요약\n\n')[1].split('\n\n## 제1장')[0]
    summary_html = '<br/><br/>'.join(e(p) for p in summary.split('\n\n'))
    width = 481.9
    cover = Table([
        [Paragraph('프로젝트명', S['label']), Paragraph('CastGuard: 근거를 설명하는 품질검사 의사결정 지원', S['value'])],
        [Paragraph('팀명', S['label']), Paragraph(e(TEAM) + ' (팀장 정가현 · 팀원 신종훈)', S['value'])],
        [Paragraph('부문', S['label']), Paragraph('중소·중견기업 재직자 부문 · 과제 ② 품질불량 조기예측 및 공정개선', S['value'])],
        [Paragraph('내용요약', S['label']), Paragraph(summary_html, S['summary'])],
    ], colWidths=[width * 0.2, width * 0.8])
    cover.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), 0.8, colors.black), ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#eef2f6')),
                               ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('VALIGN', (0, 3), (-1, 3), 'TOP'),
                               ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                               ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8)]))
    story = [Paragraph('제6회 K-인공지능 제조데이터 분석 경진대회 보고서', S['title']), cover, Spacer(1, 26),
             Paragraph('상기 본인(팀)은 위의 내용과 같이 제6회 K-인공지능 제조데이터 분석 경진대회 결과 보고서를 제출합니다.', S['center']),
             Spacer(1, 18), Paragraph('2026년 10월 8일', S['right']), Spacer(1, 10),
             Paragraph('팀장 : 정가현 &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;(서명)', S['sig']),
             Paragraph('팀원 : 신종훈 &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;(서명)', S['sig']),
             Spacer(1, 16), Paragraph('(사)중소기업기술혁신협회 귀중', S['center'])]
    body = text[text.index('## 제1장'):]
    body = body.split('\n상기 본인(팀)은 위 내용과 같이')[0]
    lines = body.splitlines(); i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1; continue
        if line.startswith('## '):
            story.extend([PageBreak(), Paragraph(e(line[3:]), S['h2'])]); i += 1; continue
        if line.startswith('### '):
            story.append(Paragraph(e(line[4:]), S['h3'])); i += 1; continue
        if line.startswith('|'):
            rows = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                rr = [v.strip() for v in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r'[: -]+', v) for v in rr):
                    rows.append(rr)
                i += 1
            cols = len(rows[0])
            ratios = {3: [.23, .32, .45], 4: [.24, .24, .26, .26], 5: [.28, .18, .18, .16, .20]}.get(cols, [1 / cols] * cols)
            table = Table([[Paragraph(e(v), S['cell']) for v in row] for row in rows], colWidths=[width * r for r in ratios], repeatRows=1, hAlign='LEFT')
            table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e4edf4')), ('LINEBELOW', (0, 0), (-1, 0), .7, colors.HexColor('#25455e')),
                                       ('LINEBELOW', (0, 1), (-1, -1), .3, colors.HexColor('#c8d4dd')), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                       ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                                       ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8)]))
            story.extend([table, Spacer(1, 13)]); continue
        story.append(Paragraph(e(line), S['p'])); i += 1

    def footer(can, doc):
        can.setFont('Body', 9); can.setFillColor(colors.HexColor('#53657b'))
        can.drawString(56.69, 24, 'CastGuard · 과제② · ' + TEAM); can.drawRightString(A4[0] - 56.69, 24, str(doc.page))
    tmp = BUILD / 'report_body.pdf'
    SimpleDocTemplate(str(tmp), pagesize=A4, leftMargin=56.69, rightMargin=56.69, topMargin=42.52, bottomMargin=42.52,
                      title='CastGuard: 근거를 설명하는 품질검사 의사결정 지원', author=TEAM).build(story, onFirstPage=footer, onLaterPages=footer)
    survey = BUILD / 'survey_appendix.pdf'; can = canvas.Canvas(str(survey), pagesize=landscape(A4)); w, h = landscape(A4)
    can.setFont('Bold', 18); can.drawString(40, h - 48, '부록 B. 설문조사 완료 화면')
    can.setFont('Body', 10); can.drawString(40, h - 70, '참가팀이 제공한 원본 화면을 그대로 첨부했습니다.')
    can.drawImage(str(ROOT / 'docs/설문조사완료.png'), 40, 35, width=w - 80, height=h - 125, preserveAspectRatio=True, anchor='c')
    can.save()
    writer = PdfWriter(); writer.append(tmp); writer.append(survey); writer.add_metadata({'/Title': 'CastGuard 품질검사 의사결정 지원', '/Author': TEAM})
    with (OUT / 'CastGuard_report.pdf').open('wb') as stream:
        writer.write(stream)
    shutil.copy2(ROOT / 'docs/설문조사완료.png', OUT / '설문조사완료.png')
    return len(PdfReader(OUT / 'CastGuard_report.pdf').pages)


if __name__ == '__main__':
    print('pages', render(MD.read_text(encoding='utf-8')))
