"""DART business-report HTML -> hierarchical, source-pinned chunks (stdlib only).

Input: a folder of DART section HTML files named <sha256>.html with <...>.meta.json
(copied read-only from 2차_실제/gongsi-research-hybrid/data/full; hashes re-checked here).
Output records keep: company, receipt no, section, heading path, kind (text|table),
table/row position, the file hash and DART viewer URL, so every hit can be traced back.
Tables are expanded (rowspan/colspan) and each row is rendered as 'header: value' pairs
so numbers stay next to their row label, column header and unit.
"""
import glob
import hashlib
import json
import os
import re
from html.parser import HTMLParser

PARSER_VERSION = 'dart-html-chunks-2'
TEXT_MAX = 700
TABLE_ROWS = 18
NUM = re.compile(r'^[\-\(]?[\d,]+(\.\d+)?\)?%?$')


def sha(b):
    return hashlib.sha256(b).hexdigest()


class _P(HTMLParser):
    """Collect a flat stream of blocks: ('head', level, text) | ('para', text) | ('table', grid, header_rows)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self.buf, self.in_p, self.p_kind = [], [], False, None
        self.tables = []          # stack of table states
        self.cell = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        t = tag.lower()
        if t == 'table':
            self.tables.append({'rows': [], 'row': None, 'thead': False, 'header_rows': 0, 'cls': a.get('class', '')})
        elif self.tables and t == 'thead':
            self.tables[-1]['thead'] = True
        elif self.tables and t == 'tr':
            self.tables[-1]['row'] = []
        elif self.tables and t in ('td', 'th'):
            self.cell = {'text': [], 'rs': int(a.get('rowspan', 1) or 1), 'cs': int(a.get('colspan', 1) or 1), 'th': t == 'th'}
        elif t == 'p' and not self.tables:
            self._flush_para()
            cls, style = a.get('class', '') or '', a.get('style', '') or ''
            m = re.match(r'section-(\d)', cls)
            self.p_kind = ('head', int(m.group(1))) if m else (('head', 4) if 'font-weight:bold' in style.replace(' ', '') else ('para', 0))
            self.in_p = True
        elif t == 'br':
            (self.cell['text'] if self.cell is not None else self.buf).append(' ')

    def handle_endtag(self, tag):
        t = tag.lower()
        if self.tables and t in ('td', 'th') and self.cell is not None:
            txt = re.sub(r'\s+', ' ', ''.join(self.cell['text'])).strip()
            if self.tables[-1]['row'] is not None:
                self.tables[-1]['row'].append((txt, self.cell['rs'], self.cell['cs'], self.cell['th']))
            self.cell = None
        elif self.tables and t == 'tr':
            tb = self.tables[-1]
            if tb['row'] is not None:
                tb['rows'].append(tb['row'])
                if tb['thead'] or all(c[3] for c in tb['row']):
                    tb['header_rows'] = len(tb['rows'])
            tb['row'] = None
        elif self.tables and t == 'thead':
            self.tables[-1]['thead'] = False
        elif t == 'table' and self.tables:
            tb = self.tables.pop()
            if not self.tables:
                self.blocks.append(('table', _grid(tb['rows']), tb['header_rows'], tb['cls']))
        elif t == 'p' and self.in_p:
            self._flush_para()

    def handle_data(self, data):
        if self.cell is not None:
            self.cell['text'].append(data)
        elif self.in_p:
            self.buf.append(data)

    def _flush_para(self):
        if self.in_p:
            txt = re.sub(r'\s+', ' ', ''.join(self.buf)).strip()
            if txt:
                kind, lvl = self.p_kind
                self.blocks.append(('head', lvl, txt) if kind == 'head' else ('para', txt))
        self.buf, self.in_p = [], False


def _grid(rows):
    """Expand rowspan/colspan into a rectangular grid of strings."""
    grid, pending = [], {}
    for r, row in enumerate(rows):
        out, c = [], 0
        cells = list(row)
        while cells or (r, c) in pending:
            if (r, c) in pending:
                out.append(pending.pop((r, c)))
                c += 1
                continue
            txt, rs, cs, _ = cells.pop(0)
            for k in range(cs):
                out.append(txt)
                for d in range(1, rs):
                    pending[(r + d, c + k)] = txt
            c += cs
        grid.append(out)
    w = max((len(x) for x in grid), default=0)
    return [x + [''] * (w - len(x)) for x in grid]


def _table_rows_text(grid, header_rows):
    if not grid:
        return [], ''
    hdr = grid[:header_rows] if header_rows else grid[:1]
    body = grid[header_rows:] if header_rows else grid[1:]
    w = len(grid[0])
    col_names = []
    for c in range(w):
        parts = []
        for h in hdr:
            if h[c] and (not parts or parts[-1] != h[c]):
                parts.append(h[c])
        col_names.append(' '.join(parts))
    lines = []
    for row in body:
        label = ' '.join(dict.fromkeys(x for x in row if x and not NUM.match(x)))[:80] if row else ''
        pairs = []
        for c, v in enumerate(row):
            if not v or (c > 0 and row[c - 1] == v and not NUM.match(v)):
                continue
            n = col_names[c]
            pairs.append(f'{n}: {v}' if n and n != v else v)
        if pairs:
            lines.append((label, ' | '.join(pairs)))
    return lines, ' | '.join(x for x in col_names if x)


def chunk_file(html, meta):
    p = _P()
    p.feed(html)
    p._flush_para()
    path = [meta['section']]
    levels = [1]                      # heading level of each path element (siblings replace each other)
    chunks, text_buf, unit_ctx = [], [], ''
    tcount = 0

    def emit(kind, text, extra=None):
        base = {'company': meta['company'], 'code': meta['code'], 'year': meta.get('year'), 'rcpNo': meta['rcpNo'],
                'section': meta['section'], 'path': list(path), 'kind': kind, 'text': text,
                'source': {'file': meta['rawHash'], 'url': meta.get('url'), 'nodeId': meta.get('nodeId')}}
        if extra:
            base['source'].update(extra)
        base['id'] = 'c-' + sha(json.dumps([meta['rawHash'], len(chunks), text], ensure_ascii=False).encode())[:20]
        chunks.append(base)

    def flush_text():
        nonlocal text_buf
        cur = ''
        for t in text_buf:
            if len(cur) + len(t) > TEXT_MAX and cur:
                emit('text', cur.strip())
                cur = ''
            cur += t + '\n'
        if cur.strip():
            emit('text', cur.strip())
        text_buf = []

    for b in p.blocks:
        if b[0] == 'head':
            flush_text()
            lvl = b[1]
            if lvl == 1:                      # top heading == the DART section itself
                path[:], levels[:] = [b[2][:80]], [1]
                continue
            while len(levels) > 1 and levels[-1] >= lvl:
                path.pop(); levels.pop()
            path.append(b[2][:80]); levels.append(lvl)
        elif b[0] == 'para':
            text_buf.append(b[1])
        else:
            grid, hdr, cls = b[1], b[2], b[3]
            flat = ' '.join(x for r in grid for x in r)
            if cls == 'nb' or (len(grid) <= 2 and ('단위' in flat or '기준일' in flat) and len(flat) < 120):
                unit_ctx = re.sub(r'\s+', ' ', flat)[:120]
                continue
            flush_text()
            tcount += 1
            lines, cols = _table_rows_text(grid, hdr)
            if not lines:
                continue
            for i in range(0, len(lines), TABLE_ROWS):
                part = lines[i:i + TABLE_ROWS]
                head = f"[표 {tcount}] {' > '.join(path[1:]) or meta['section']}" + (f' ({unit_ctx})' if unit_ctx else '')
                emit('table', head + '\n' + '\n'.join(l for _, l in part),
                     {'table': tcount, 'rows': [i + 1, i + len(part)], 'unit': unit_ctx, 'columns': cols[:300]})
            unit_ctx = ''
    flush_text()
    return chunks


def build(src_dir):
    from pathlib import Path
    metas = [json.loads(Path(f).read_text(encoding='utf-8')) for f in sorted(glob.glob(os.path.join(src_dir, '*.meta.json')))]
    chunks, files, bad = [], [], []
    for m in sorted(metas, key=lambda m: (m['code'], int(m['nodeId']))):
        fp = os.path.join(src_dir, m['rawHash'] + '.html')
        if not os.path.exists(fp):
            bad.append({'file': m['rawHash'], 'reason': 'missing'})
            continue
        raw = Path(fp).read_bytes()
        if sha(raw) != m['rawHash']:
            bad.append({'file': m['rawHash'], 'reason': 'hash_mismatch'})
            continue
        cs = chunk_file(raw.decode('utf-8', errors='replace'), m)
        chunks += cs
        files.append({'code': m['code'], 'section': m['section'], 'rawHash': m['rawHash'], 'chunks': len(cs), 'rcpNo': m['rcpNo']})
    manifest = {'parser': PARSER_VERSION, 'files': files, 'rejected': bad, 'chunks': len(chunks),
                'corpusHash': sha(json.dumps([c['id'] for c in chunks]).encode()),
                'companies': sorted({c['company'] for c in chunks})}
    return chunks, manifest
