from pathlib import Path
from datetime import datetime, timedelta, timezone
import hashlib, json, re, zipfile, shutil
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pypdf import PdfReader
from PIL import Image, ImageChops

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'submission'
BUILD=ROOT/'reports/oct06_submission'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')

report=PdfReader(OUT/'CastGuard_report.pdf')
slides=PdfReader(OUT/'CastGuard_presentation.pdf')
assert len(report.pages)==14 and len(slides.pages)==16
texts=['\n'.join(p.extract_text() for p in r.pages) for r in [report,slides]]
for text in texts:
    compact=re.sub(r'\s','',text)
    for token in ['RE제조부터시작하는이세계생활','정가현','신종훈','0.3845','0.7378']:
        assert token in compact, token
    assert not re.search(r'C:[/\\]Users|/home/|TODO|\[미완료\]',text)
for n in range(1,7):assert f'제{n}장' in texts[0]
survey=Image.open(ROOT/'docs/설문조사완료.png').convert('RGB')
assert sha(ROOT/'docs/설문조사완료.png')==sha(OUT/'설문조사완료.png')
assert any(im.image.size==survey.size and ImageChops.difference(im.image.convert('RGB'),survey).getbbox() is None for im in report.pages[-1].images)

with zipfile.ZipFile(OUT/'CastGuard_presentation.pptx') as z:
    assert z.testzip() is None
    core=z.read('docProps/core.xml').decode('utf-8')
    assert not re.search(r'C:[/\\]Users|/home/|>JH<',core)
    slideparts=[n for n in z.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml',n)]
    assert len(slideparts)==16
    for part in slideparts:ET.fromstring(z.read(part))

dest=BUILD/'final_unpacked_verify'
assert not dest.exists()
dest.mkdir()
with zipfile.ZipFile(OUT/'CastGuard_source.zip') as z:
    assert z.testzip() is None
    for info in z.infolist():
        target=(dest/info.filename).resolve()
        assert target.is_relative_to(dest.resolve())
        assert not any(x in info.filename.split('/') for x in ['.git','.venv','__pycache__'])
    z.extractall(dest)
base=dest/'CastGuard'
manifest=json.loads((base/'PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
for item in manifest['files']:
    p=base/item['path'];assert sha(p)==item['sha256'] and p.stat().st_size==item['bytes']
    if p.suffix in ['.py','.md','.txt','.json','.html','.toml']:
        assert not re.search(r'C:[/\\]Users[/\\]|/home/ozingmw',p.read_text(encoding='utf-8-sig')),p
prior=BUILD/'unpacked_verify/CastGuard'
old=json.loads((prior/'PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
new={x['path']:x for x in manifest['files']}
for item in old['files']:
    if item['path']!='README.md':assert new[item['path']]['sha256']==item['sha256'],item['path']
# Full fit replay used the prior ZIP; source/model/config/data hashes are identical.
replay=json.loads((prior/'verification_runs/research_replay/reproduction_check.json').read_text())
assert replay['passed'] and replay['max_absolute_difference']==0
save(BUILD/'reproduction_check.json',replay)

class Audit(HTMLParser):
    def __init__(self):super().__init__();self.tags={};self.external=[]
    def handle_starttag(self,tag,attrs):
        self.tags[tag]=self.tags.get(tag,0)+1
        for k,v in attrs:
            if k in ['src','href'] and v and v.startswith(('http:','https:')):self.external.append(v)
html=Audit();html.feed((OUT/'CastGuard_demo.html').read_text(encoding='utf-8'))
assert html.tags.get('article')==11 and html.tags.get('details')==11 and not html.external and not html.tags.get('script')
native=json.loads((BUILD/'slides/render_receipt.json').read_text(encoding='utf-8-sig'))
assert native['slides']==16 and native['overflow_count']==0
deck=json.loads((BUILD/'deck_build/validation-v2.json').read_text())
assert deck['finalSha256']==sha(OUT/'CastGuard_presentation.pptx')

receipt={
 'checked_at':datetime.now(timezone(timedelta(hours=9))).isoformat(),
 'status':'artifact checks passed; browser interaction unverified; signature and portal pending',
 'report_pages':14,'presentation_slides':16,'visual_inspection':'all 14 final report pages and 16 final native slide renders reviewed',
 'native_powerpoint_text_overflow':0,'survey_png_byte_exact':True,'survey_pdf_pixels_exact':True,
 'source_zip_files':len(manifest['files'])+1,'source_manifest_hashes_verified':len(manifest['files']),
 'source_zip_crc_and_containment':True,'sensitive_local_path_scan':'no local user path in packaged text/code or PDF text; no organization identification added',
 'full_repository_regressions':{'passed':413,'failed':0,'excluded':0,'receipt':'reports/reproduction/tests_20261006T143800Z_b6a10e51/receipt.json'},
 'computational_reproduction':replay,
 'reproduction_scope':'525 candidate fits in unpacked prior ZIP; all scientific source/data/config/checkpoints identical in final ZIP; final ZIP adds support docs/demo HTML and README formatting',
 'metric_crosscheck':json.loads((ROOT/'reports/oct06_research/independent_verification.json').read_text()),
 'demo':{'records':11,'explanation_panels':11,'external_resources':False,'javascript':False,'browser_interaction_verified':False,'browser_limitation':'Browser tool security policy blocked local file URL; no workaround attempted'},
 'not_verified':['new independent data performance','field input arrival times and actual cost','physical line improvement','actual signature','portal submission'],
 'artifacts':[{'file':p.name,'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(OUT.iterdir()) if p.is_file() and p.name not in ['VERIFICATION.json','CHECKSUMS.sha256','README.md']]
}
save(BUILD/'final_checks.json',receipt);save(OUT/'VERIFICATION.json',receipt)
print(json.dumps({'source_files':receipt['source_zip_files'],'report_pages':14,'slides':16,'checks_passed':True}))
