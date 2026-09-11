"""Conservative DOCX text-node edits and UTF-8 plain-text rewrites."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import re
from xml.dom import minidom, Node
from zipfile import ZipFile

from app.models import RewriteResult

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


@dataclass(frozen=True)
class ContentBlock:
    id: str
    text: str
    context: str = ''

    @property
    def character_budget(self) -> int:
        return len(self.text)


def preservation_issue(original: str, replacement: str) -> str:
    if Counter(re.findall(r'\d+(?:[.,]\d+)*', original)) != Counter(re.findall(r'\d+(?:[.,]\d+)*', replacement)):
        return 'Numeric content changed.'
    for pattern in (r'https?://[^\s<>]+', r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', r'\[\d+(?:[ ,–-]\d+)*\]'):
        if Counter(re.findall(pattern, original)) != Counter(re.findall(pattern, replacement)):
            return 'A URL, email address, or numbered citation changed.'
    return ''


def _decision(block: ContentBlock, replacement: str, limit_length: bool) -> RewriteResult:
    if replacement == block.text:
        return RewriteResult(block.id, block.text, block.text, 'unchanged')
    reason = preservation_issue(block.text, replacement)
    if not replacement.strip() or any(c in replacement for c in '\r\n\t'):
        reason = 'Replacement was empty or introduced a line break or tab.'
    if reason:
        return RewriteResult(block.id, block.text, block.text, 'skipped_preservation', reason)
    if limit_length and len(replacement) > block.character_budget:
        return RewriteResult(block.id, block.text, block.text, 'skipped_expansion', 'Replacement exceeded the original text length. Layout-sensitive content was kept original.')
    return RewriteResult(block.id, block.text, replacement, 'rewritten')


def _read_txt(path: Path):
    raw = path.read_bytes()
    bom = raw.startswith(b'\xef\xbb\xbf')
    text = raw.decode('utf-8-sig')
    if '\x00' in text:
        raise ValueError('Please upload a UTF-8 text file, not a binary file.')
    return bom, re.split(r'(\r\n|\r|\n)', text)


def extract_txt(path: Path) -> list[ContentBlock]:
    _, parts = _read_txt(path)
    return [ContentBlock(f'line-{i // 2 + 1}', parts[i].strip()) for i in range(0, len(parts), 2) if parts[i].strip()]


def rewrite_txt(source: Path, output: Path, replacements: dict[str, str]) -> list[RewriteResult]:
    bom, parts = _read_txt(source)
    results = []
    for i in range(0, len(parts), 2):
        line = parts[i]
        text = line.strip()
        if not text:
            continue
        block = ContentBlock(f'line-{i // 2 + 1}', text)
        result = _decision(block, replacements.get(block.id, text).strip(), False)
        results.append(result)
        if result.status == 'rewritten':
            start = len(line) - len(line.lstrip())
            parts[i] = line[:start] + result.rewritten + line[start + len(text):]
    output.write_bytes((b'\xef\xbb\xbf' if bom else b'') + ''.join(parts).encode('utf-8'))
    return results


def _text(element) -> str:
    return ''.join(c.data for c in element.childNodes if c.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE))


def _ancestor(element, name: str):
    parent = element.parentNode
    while parent:
        if parent.namespaceURI == W and parent.localName == name:
            return parent
        parent = parent.parentNode
    return None


def _elements(element, name: str):
    return element.getElementsByTagNameNS(W, name)


def _docx_units(path: Path):
    documents = {}
    units = []
    skipped = []
    with ZipFile(path) as archive:
        infos = archive.infolist()
        names = [i.filename for i in infos]
        if len(names) != len(set(names)) or 'word/document.xml' not in names:
            raise ValueError('This is not a supported DOCX file.')
        if len(names) > 10000 or sum(i.file_size for i in infos) > 150 * 1024 * 1024:
            raise ValueError('DOCX expanded content exceeds the processing limit.')
        if any('vbaProject' in n or n.startswith('_xmlsignatures/') for n in names):
            raise ValueError('Signed or macro-enabled Word documents are not supported.')
        parts = sorted(n for n in names if re.fullmatch(r'word/(document|header\d+|footer\d+|footnotes|endnotes)\.xml', n))
        for part in parts:
            raw = archive.read(part)
            if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
                raise ValueError('DOCX XML declarations containing entities are not supported.')
            dom = minidom.parseString(raw)
            documents[part] = dom
            for p_index, paragraph in enumerate(_elements(dom, 'p')):
                texts = list(_elements(paragraph, 't'))
                context = ''.join(_text(t) for t in texts)
                if not context.strip():
                    continue
                pid = f'{part}:p{p_index}'
                # Preserve fields, review markup, content controls, text boxes,
                # anchored/inline art and fixed-height table rows as authored.
                protected = any(_elements(paragraph, tag) for tag in ('fldChar', 'instrText', 'fldSimple', 'drawing', 'pict', 'del', 'ins', 'sdt'))
                protected = protected or any(_ancestor(paragraph, tag) for tag in ('txbxContent', 'sdt', 'ins', 'del'))
                row = _ancestor(paragraph, 'tr')
                if row and any(h.getAttributeNS(W, 'hRule') == 'exact' for h in _elements(row, 'trHeight')):
                    protected = True
                if protected:
                    skipped.append(RewriteResult(pid, context, context, 'skipped_complex_layout', 'Field, review markup, image, text box, content control, or fixed-height row retained unchanged.'))
                    continue
                # Each formatted run remains intact. Adjacent equal-style runs
                # may be rewritten together; mixed-style boundaries remain.
                groups = []
                for node in texts:
                    if _ancestor(node, 'hyperlink'):
                        skipped.append(RewriteResult(f'{pid}:link{len(skipped)}', _text(node), _text(node), 'skipped_hyperlink', 'Hyperlink text and target retained unchanged.'))
                        groups.append((None, []))
                        continue
                    run = _ancestor(node, 'r')
                    if run is None:
                        continue
                    props = [c.toxml() for c in run.childNodes if c.namespaceURI == W and c.localName == 'rPr']
                    # Breaks and tabs are layout boundaries, not editable text.
                    boundary = any(c.namespaceURI == W and c.localName not in ('rPr', 't') for c in run.childNodes)
                    signature = ''.join(props)
                    if not boundary and groups and groups[-1][0] == signature:
                        groups[-1][1].append(node)
                    else:
                        groups.append((signature, [node]))
                    if boundary:
                        groups.append((None, []))
                for g_index, (_, nodes) in enumerate(groups):
                    text = ''.join(_text(t) for t in nodes)
                    if text.strip():
                        units.append((ContentBlock(f'{pid}:r{g_index}', text, context), nodes, part))
    return documents, units, skipped


def extract_docx(path: Path) -> list[ContentBlock]:
    _, units, _ = _docx_units(path)
    return [block for block, _, _ in units]


def rewrite_docx(source: Path, output: Path, replacements: dict[str, str]) -> list[RewriteResult]:
    documents, units, results = _docx_units(source)
    changed = set()
    for block, nodes, part in units:
        candidate = replacements.get(block.id, block.text)
        # Preserve whitespace at formatting boundaries.
        prefix = block.text[:len(block.text) - len(block.text.lstrip())]
        suffix = block.text[len(block.text.rstrip()):]
        candidate = prefix + candidate.strip() + suffix
        result = _decision(block, candidate, True)
        results.append(result)
        if result.status != 'rewritten':
            continue
        for i, node in enumerate(nodes):
            while node.firstChild:
                node.removeChild(node.firstChild)
            node.appendChild(documents[part].createTextNode(candidate if i == 0 else ''))
            node.setAttributeNS('http://www.w3.org/XML/1998/namespace', 'xml:space', 'preserve')
        changed.add(part)
    with ZipFile(source) as original, ZipFile(output, 'w') as rewritten:
        rewritten.comment = original.comment
        for info in original.infolist():
            payload = documents[info.filename].toxml(encoding='UTF-8') if info.filename in changed else original.read(info.filename)
            rewritten.writestr(info, payload)
    # Every package part outside edited text XML remains byte-for-byte identical.
    with ZipFile(source) as original, ZipFile(output) as rewritten:
        assert original.namelist() == rewritten.namelist()
        for name in original.namelist():
            if name not in changed:
                assert original.read(name) == rewritten.read(name)
    return results
