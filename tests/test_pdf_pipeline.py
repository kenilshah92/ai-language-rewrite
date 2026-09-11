from pathlib import Path
import pymupdf as fitz
from app.pdf_rewriter import prepare_pdf_blocks
from app.pdf_pipeline import process_pdf


def sample(path):
    with fitz.open() as d:
        p=d.new_page(width=720,height=405)
        p.insert_text((50,80),'Customer demand grew quickly and the support team needed a better way to manage daily work.',fontsize=12)
        p.insert_text((50,102),'The 12 agents assigned each request to the right person for a clear response.',fontsize=12)
        d.save(path)


class RepairingModel:
    model='test-model'
    prompt_text='Test editorial instructions'
    prompt_sha256='test-prompt-hash'
    response_ids=[]
    def __init__(self):self.calls=[]
    def rewrite(self,blocks,repairs=None):
        self.calls.append((blocks,repairs))
        assert len(blocks)==1
        assert 'Customer demand' in blocks[0].text and '12 agents' in blocks[0].text
        return {blocks[0].id: 'The 12 agents handled growing demand.' if repairs else 'Agents handled growing demand.'}


def test_paragraph_first_and_targeted_repair(tmp_path):
    source=tmp_path/'in.pdf';output=tmp_path/'out.pdf';sample(source)
    model=RepairingModel();r=process_pdf(source,output,model)
    assert len(model.calls)==2
    assert model.calls[1][1]
    assert r['summary']=={'rewritten':1}
    row=r['blocks'][0]
    assert row['initial_proposed']=='Agents handled growing demand.'
    assert row['attempts'][0]['status']=='skipped_numbers'
    assert row['attempts'][1]['status']=='rewritten'
    assert r['prompt_snapshot']==model.prompt_text
    with fitz.open(output) as d:assert '12 agents' in d[0].get_text()


def test_repair_failure_keeps_original(tmp_path):
    source=tmp_path/'in.pdf';output=tmp_path/'out.pdf';sample(source)
    class BrokenRepair(RepairingModel):
        def rewrite(self,blocks,repairs=None):
            if repairs:raise RuntimeError('temporary failure')
            return super().rewrite(blocks)
    report=process_pdf(source,output,BrokenRepair())
    assert report['summary']=={'skipped_numbers':1}
    assert report['repair_errors']
    with fitz.open(source) as a,fitz.open(output) as b:
        assert a[0].get_pixmap().samples==b[0].get_pixmap().samples


def test_repair_is_bounded(tmp_path):
    source=tmp_path/'in.pdf';output=tmp_path/'out.pdf';sample(source)
    class AlwaysInvalid(RepairingModel):
        def rewrite(self,blocks,repairs=None):
            self.calls.append(repairs)
            return {blocks[0].id:'Agents handled demand' + '.'*len(self.calls)}
    m=AlwaysInvalid();r=process_pdf(source,output,m)
    assert len(m.calls)==3
    assert r['summary']=={'skipped_numbers':1}
    assert len(r['blocks'][0]['attempts'])==3


def test_disconnected_labels_and_mixed_styles_are_protected(tmp_path):
    from dataclasses import replace
    from app.pdf_rewriter import _layout_issue, rewrite_pdf
    spans = [{'text': 'Label', 'font': 'Helvetica', 'size': 10, 'color': 0}]
    assert _layout_issue([], spans + [dict(spans[0], size=20)])
    lines = [{'bbox': [10, 10, 50, 22], 'spans': spans},
             {'bbox': [200, 10, 250, 22], 'spans': spans}]
    assert _layout_issue(lines, spans)
    source = tmp_path / 'in.pdf'; output = tmp_path / 'out.pdf'; sample(source)
    with fitz.open(source) as d:
        blocks = [replace(b, layout_issue='Separated labels') for b in prepare_pdf_blocks(d)]
    result = rewrite_pdf(source, output, {b.id: 'Changed wording' for b in blocks}, prepared_blocks=blocks)
    assert all(r.status == 'skipped_complex_layout' for r in result)
    with fitz.open(source) as a, fitz.open(output) as b:
        assert a[0].get_pixmap().samples == b[0].get_pixmap().samples
