"""Generate prose first, repair fit failures, then render once from the source."""
import hashlib
from pathlib import Path

import pymupdf as fitz
from app.pdf_rewriter import prepare_pdf_blocks, repair_constraints, rewrite_pdf, report_to_dict

REPAIRABLE = {'skipped_numbers', 'skipped_missing_glyphs', 'skipped_overflow', 'skipped_empty', 'skipped_preservation'}


def process_pdf(source: Path, output: Path, humanizer, min_font_scale: float = .85) -> dict:
    with fitz.open(source) as document:
        if document.needs_pass:
            raise ValueError('Password-protected PDFs are not supported.')
        blocks = prepare_pdf_blocks(document)
    if not blocks:
        raise ValueError('No editable text layer was found.')
    proposals = humanizer.rewrite(blocks)
    initial = dict(proposals)
    history = {b.id: [] for b in blocks}
    by_id = {b.id: b for b in blocks}
    repair_errors = []
    for attempt in range(3):  # Initial check plus at most two targeted repair rounds.
        checked = rewrite_pdf(source, output, proposals, min_font_scale, prepared_blocks=blocks, dry_run=True)
        for result in checked:
            if attempt == 0 or not history[result.block_id] or history[result.block_id][-1]['proposed'] != proposals[result.block_id]:
                history[result.block_id].append({'round': attempt, 'proposed': proposals[result.block_id], 'status': result.status, 'reason': result.message})
        rejected = [r for r in checked if r.status in REPAIRABLE]
        if not rejected or attempt == 2:
            break
        repairs = {}
        with fitz.open(source) as document:
            for r in rejected:
                constraints = repair_constraints(document, by_id[r.block_id], proposals[r.block_id])
                if r.status == 'skipped_overflow':
                    constraints['maximum_characters'] = max(1, int(len(proposals[r.block_id]) * .8))
                repairs[r.block_id] = {'proposed': proposals[r.block_id], 'reason': r.message, **constraints}
        try:
            updates = humanizer.rewrite([by_id[r.block_id] for r in rejected], repairs=repairs)
        except Exception:
            # Keep usable rewrites when an optional repair request fails.
            repair_errors.append('A targeted repair request failed; rejected blocks were kept original.')
            break
        if all(updates[key] == proposals[key] for key in updates):
            break
        proposals.update(updates)
    results = rewrite_pdf(source, output, proposals, min_font_scale, prepared_blocks=blocks)
    report = report_to_dict(results)
    for row in report['blocks']:
        row['initial_proposed'] = initial[row['block_id']]
        row['attempts'] = history[row['block_id']]
        b = by_id[row['block_id']]
        row['page'] = b.page_index + 1
        row['original_rect'] = list(b.rect)
    total = sum(len(b.text) for b in blocks)
    changed = sum(len(r.original) for r in results if r.status == 'rewritten')
    report.update({
        'pipeline_version': 'paragraph-first-v3',
        'model': humanizer.model,
        'prompt_sha256': humanizer.prompt_sha256,
        'prompt_snapshot': humanizer.prompt_text,
        'response_ids': humanizer.response_ids,
        'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'rewritten_text_coverage': round(changed / max(total, 1), 4),
        'repair_errors': repair_errors,
    })
    return report
