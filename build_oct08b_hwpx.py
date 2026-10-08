"""Fill the official HWPX report form with the 10/8 report text.

Cover table (프로젝트명/팀명/내용요약), date and signature names are filled in place;
each chapter's placeholder text and 작성 요령 boxes are replaced by the report
paragraphs; markdown tables become ' | '-separated lines (convert with 한글's
문자열을 표로 if desired); the sample survey image is replaced by the real capture.
Output: reports/oct08b_submission/CastGuard_report.hwpx (editable in 한글).
"""
from pathlib import Path
import io
import re
import xml.etree.ElementTree as ET
import zipfile

from PIL import Image

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / 'docs/경진대회 결과보고서 양식_중소,중견기업 재직자 부문.hwpx'
MD = ROOT / 'reports/oct08b_submission/CastGuard_report.md'
OUT = ROOT / 'reports/oct08b_submission/CastGuard_report.hwpx'
BODY_CHAR, HEAD_CHAR, PARA = '8', '11', '20'


def esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def para(text, char=BODY_CHAR, break_page=False):
    return (f'<hp:p id="0" paraPrIDRef="{PARA}" styleIDRef="0" pageBreak="{int(break_page)}" columnBreak="0" merged="0">'
            f'<hp:run charPrIDRef="{char}"><hp:t>{esc(text)}</hp:t></hp:run></hp:p>')


def chapter_paragraphs(block):
    out = []
    lines = block.splitlines(); i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1; continue
        if line.startswith('### '):
            out.append(para(line[4:], HEAD_CHAR)); i += 1; continue
        if line.startswith('|'):
            rows = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                cells = [v.strip() for v in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r'[: -]+', v) for v in cells):
                    rows.append(cells)
                i += 1
            out.append(para('[표] ' + ' | '.join(rows[0]), HEAD_CHAR))
            for r in rows[1:]:
                out.append(para(' | '.join(r)))
            out.append(para(''))
            continue
        out.append(para(line)); i += 1
    return ''.join(out)


def fill_after(x, label, replacement, pattern):
    i = x.find(label); assert i > 0, label
    m = re.compile(pattern).search(x, i); assert m, label
    return x[:m.start()] + replacement + x[m.end():]


def main():
    md = MD.read_text(encoding='utf-8')
    summary = md.split('## 내용요약\n\n')[1].split('\n\n## 제1장')[0].split('\n\n')
    chapters = {}
    for n in range(1, 7):
        start = md.index(f'## 제{n}장')
        end = md.index(f'## 제{n + 1}장') if n < 6 else md.index('## 부록 A')
        body = md[start:end].split('\n', 1)[1]
        chapters[n] = body
    appendix = md[md.index('## 부록 A'):].split('\n', 1)[1].split('\n상기 본인(팀)은')[0]

    z = zipfile.ZipFile(TEMPLATE)
    x = z.read('Contents/section0.xml').decode('utf-8')
    # Cover table
    x = fill_after(x, '프로젝트명</hp:t>', '<hp:run charPrIDRef="19"><hp:t>CastGuard: 근거를 설명하는 품질검사 의사결정 지원</hp:t></hp:run>', r'<hp:run charPrIDRef="19"/>')
    x = fill_after(x, '팀명</hp:t>', '<hp:t>RE제조부터시작하는이세계생활 (팀장 정가현 · 팀원 신종훈)</hp:t>', r'<hp:t/>')
    i = x.find('내용요약</hp:t>'); m = re.compile(r'<hp:run charPrIDRef="(\d+)"/>|<hp:t/>').search(x, i); assert m
    if m.group(0) == '<hp:t/>':
        x = x[:m.start()] + f'<hp:t>{esc(summary[0])}</hp:t>' + x[m.end():]
    else:
        x = x[:m.start()] + f'<hp:run charPrIDRef="{m.group(1)}"><hp:t>{esc(summary[0])}</hp:t></hp:run>' + x[m.end():]
    j = x.find('</hp:p>', m.start()) + len('</hp:p>')
    extra = ''.join(f'<hp:p id="2147483648" paraPrIDRef="30" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="19"><hp:t>{esc(s)}</hp:t></hp:run></hp:p>' for s in summary[1:])
    x = x[:j] + extra + x[j:]
    # Date and signatures
    x = x.replace('2026년    월    일', '2026년 10월  8일', 1)
    x = x.replace('팀장 :                 (서명)', '팀장 : 정가현           (서명)', 1)
    x = x.replace('팀원 :                 (서명)', '팀원 : 신종훈           (서명)', 1)
    k = x.find('팀원 :                 (서명)')
    if k > 0:
        ps = x.rfind('<hp:p ', 0, k); pe = x.find('</hp:p>', k) + len('</hp:p>')
        x = x[:ps] + x[pe:]
    # Chapters: keep the heading paragraph, replace everything up to the next heading
    for n in range(1, 7):
        h = x.find(f'<hp:t>제{n}장.'); assert h > 0, n
        head_end = x.find('</hp:p>', h) + len('</hp:p>')
        if n < 6:
            nxt = x.find(f'<hp:t>제{n + 1}장.'); boundary = x.rfind('<hp:p ', 0, nxt)
        else:
            boundary = x.rfind('<hp:p ', 0, x.find('□ 경진대회 만족도 조사'))
        content = chapter_paragraphs(chapters[n])
        if n == 6:
            content += para('부록 A. 근거와 해석 범위', HEAD_CHAR) + chapter_paragraphs(appendix) + para('')
        x = x[:head_end] + content + x[boundary:]
    # Survey image: replace sample with the real capture and fix the aspect ratio
    img = Image.open(ROOT / 'docs/설문조사완료.png').convert('RGB')
    w, h = img.size
    buf = io.BytesIO(); img.save(buf, format='BMP'); bmp = buf.getvalue()
    org_w = 142200; org_h = int(org_w * h / w); cur_w = 46604; cur_h = int(cur_w * h / w)
    pic_s = x.find('<hp:pic '); pic_e = x.find('</hp:pic>', pic_s) + len('</hp:pic>')
    pic = x[pic_s:pic_e]
    pic = re.sub(r'<hp:orgSz width="\d+" height="\d+"/>', f'<hp:orgSz width="{org_w}" height="{org_h}"/>', pic)
    pic = re.sub(r'<hp:curSz width="\d+" height="\d+"/>', f'<hp:curSz width="{cur_w}" height="{cur_h}"/>', pic)
    pic = re.sub(r'centerY="\d+"', f'centerY="{cur_h // 2}"', pic)
    pic = re.sub(r'<hc:pt2 x="\d+" y="\d+"/>', f'<hc:pt2 x="{org_w}" y="{org_h}"/>', pic)
    pic = re.sub(r'<hc:pt3 x="\d+" y="\d+"/>', f'<hc:pt3 x="0" y="{org_h}"/>', pic)
    pic = re.sub(r'<hp:imgClip left="0" right="\d+" top="0" bottom="\d+"/>', f'<hp:imgClip left="0" right="{org_w}" top="0" bottom="{org_h}"/>', pic)
    pic = re.sub(r'<hp:imgDim dimwidth="\d+" dimheight="\d+"/>', f'<hp:imgDim dimwidth="{org_w}" dimheight="{org_h}"/>', pic)
    pic = re.sub(r'<hp:sz width="(\d+)" widthRelTo="ABSOLUTE" height="\d+"', rf'<hp:sz width="\1" widthRelTo="ABSOLUTE" height="{cur_h}"', pic)
    x = x[:pic_s] + pic + x[pic_e:]
    x = x.replace('<hp:t>예 시</hp:t>', '<hp:t>설문조사 완료 화면</hp:t>')
    ET.fromstring(x.encode('utf-8'))  # well-formedness check
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT, 'w') as out:
        out.writestr(zipfile.ZipInfo('mimetype'), z.read('mimetype'), compress_type=zipfile.ZIP_STORED)
        for info in z.infolist():
            if info.filename == 'mimetype':
                continue
            data = z.read(info.filename)
            if info.filename == 'Contents/section0.xml':
                data = x.encode('utf-8')
            elif info.filename == 'BinData/image1.bmp':
                data = bmp
            elif info.filename == 'Preview/PrvText.txt':
                data = ('제6회 K-인공지능 제조데이터 분석 경진대회 보고서 / CastGuard: 근거를 설명하는 품질검사 의사결정 지원 / ' + summary[0][:300]).encode('utf-8')
            out.writestr(info.filename, data, compress_type=zipfile.ZIP_DEFLATED)
    print('written', OUT, OUT.stat().st_size, 'bytes; chapters', len(chapters))


if __name__ == '__main__':
    main()
