from zipfile import ZipFile
from xml.dom import minidom
from app.document_rewriter import extract_docx, rewrite_docx, extract_txt, rewrite_txt

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


def make_docx(path):
    xml = f'''<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{W}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><w:body>
    <w:p><w:pPr><w:spacing w:after="120"/></w:pPr><w:r><w:rPr><w:rFonts w:ascii="Arial"/><w:sz w:val="24"/></w:rPr><w:t>We are delighted to announce our launch.</w:t></w:r></w:p>
    <w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Bold introduction </w:t></w:r><w:r><w:t>plain ending.</w:t></w:r><w:hyperlink r:id="rId2"><w:r><w:t>Read more</w:t></w:r></w:hyperlink></w:p>
    <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Streamlined operational solutions</w:t></w:r></w:p></w:tc></w:tr><w:tr><w:trPr><w:trHeight w:val="100" w:hRule="exact"/></w:trPr><w:tc><w:p><w:r><w:t>Fixed row content</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
    <w:p><w:r><w:fldChar w:fldCharType="begin"/><w:instrText>PAGE</w:instrText><w:t>1</w:t></w:r></w:p>
    <w:p><w:r><w:drawing/><w:t>Image caption</w:t></w:r></w:p>
    <w:sectPr><w:pgSz w:w="12240" w:h="15840"/></w:sectPr></w:body></w:document>'''
    with ZipFile(path, 'w') as z:
        z.writestr('word/document.xml', xml)
        z.writestr('word/styles.xml', '<styles>unchanged</styles>')
        z.writestr('word/media/image1.png', b'original image bytes')
        z.writestr('word/_rels/document.xml.rels', '<relationships>unchanged</relationships>')
        z.writestr('[Content_Types].xml', '<Types/>')


def test_docx_retains_assets_styles_runs_and_protected_content(tmp_path):
    source = tmp_path / 'source.docx'
    output = tmp_path / 'out.docx'
    make_docx(source)
    blocks = extract_docx(source)
    assert len(blocks) == 4
    assert all('Read more' != b.text for b in blocks)
    assert blocks[1].context == 'Bold introduction plain ending.Read more'
    replacements = {blocks[0].id: 'We are launching.', blocks[1].id: 'Introduction', blocks[3].id: 'Clear processes'}
    results = rewrite_docx(source, output, replacements)
    assert sum(r.status == 'rewritten' for r in results) == 3
    assert sum(r.status == 'skipped_complex_layout' for r in results) == 3
    with ZipFile(source) as a, ZipFile(output) as b:
        for name in a.namelist():
            if name != 'word/document.xml':
                assert a.read(name) == b.read(name)
        before = minidom.parseString(a.read('word/document.xml'))
        after = minidom.parseString(b.read('word/document.xml'))
        for tag in ('rPr', 'pPr', 'sectPr', 'hyperlink', 'drawing', 'trPr'):
            assert [x.toxml() for x in before.getElementsByTagNameNS(W, tag)] == [x.toxml() for x in after.getElementsByTagNameNS(W, tag)]
        assert len(before.getElementsByTagNameNS(W, 'r')) == len(after.getElementsByTagNameNS(W, 'r'))
        assert b'Introduction ' in b.read('word/document.xml')
        assert b'Fixed row content' in b.read('word/document.xml')


def test_docx_rejects_expansion(tmp_path):
    source = tmp_path / 'source.docx'
    output = tmp_path / 'out.docx'
    make_docx(source)
    blocks = extract_docx(source)
    results = rewrite_docx(source, output, {blocks[0].id: 'Many words ' * 100})
    assert any(r.status == 'skipped_expansion' for r in results)


def test_txt_preserves_bom_whitespace_and_line_endings(tmp_path):
    source = tmp_path / 'in.txt'
    output = tmp_path / 'out.txt'
    source.write_bytes(b'\xef\xbb\xbf  Original content  \r\n\r\n\tThere are 12 teams.\nVisit https://example.com\r')
    blocks = extract_txt(source)
    results = rewrite_txt(source, output, {blocks[0].id: 'Clear content', blocks[1].id: 'There are teams.', blocks[2].id: 'Visit https://other.example'})
    assert output.read_bytes() == b'\xef\xbb\xbf  Clear content  \r\n\r\n\tThere are 12 teams.\nVisit https://example.com\r'
    assert [r.status for r in results] == ['rewritten', 'skipped_preservation', 'skipped_preservation']
