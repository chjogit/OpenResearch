"""Runs the copied (4373) official-source verifiers. Each run re-hashes the stored
source files and re-binds table cells; no network access, no model calls."""
import hashlib
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / 'vendor'


class Cancelled(Exception):
    pass


def vendor_tree_digest():
    h = hashlib.sha256()
    for p in sorted(VENDOR.rglob('*')):
        if p.is_file():
            h.update(p.relative_to(VENDOR).as_posix().encode())
            h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def run_script(script, ctx=None, timeout=60):
    """Run a vendor script, honouring cancellation and keeping the heartbeat alive."""
    proc = subprocess.Popen(['node', str(VENDOR / script)], cwd=VENDOR, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding='utf-8')
    start = time.monotonic()
    try:
        while True:
            try:
                out, err = proc.communicate(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                if ctx is not None:
                    ctx.heartbeat()
                    if ctx.cancelled():
                        proc.kill()
                        proc.communicate()
                        raise Cancelled()
                if time.monotonic() - start > timeout:
                    proc.kill()
                    proc.communicate()
                    raise ValueError(f'{script} 시간 초과({timeout}초)')
    finally:
        if proc.poll() is None:
            proc.kill()
    if proc.returncode != 0:
        raise ValueError(f'{script} 원문 대조 실패: ' + (err or '').strip()[-400:])
    return json.loads(out)


DOC_FIELDS = ('id', 'company', 'name', 'title', 'rcpNo', 'url', 'landingUrl', 'publishedDate',
              'ingestedAt', 'rawHash', 'parserVersion', 'scope', 'unit', 'periods', 'kind', 'section', 'checkedAt')


def load_corpus(ctx=None):
    """Verified official corpus. Idempotent per vendor tree digest (a changed file changes the key)."""
    tree = vendor_tree_digest()
    key = 'official-corpus:' + tree
    if ctx is not None:
        cached = ctx.store.call_result(key)
        if cached is not None:
            ctx.step('저장된 원문 대조 결과 재사용 (같은 원문 파일 해시)')
            return cached
    if ctx is not None:
        ctx.step('재무 원문 HTML 해시·표 셀 대조 중')
    fin = run_script('valuation.mjs', ctx)
    if ctx is not None:
        ctx.tool_call()
        ctx.step('거시 원문(한국은행·연준 H.10) 대조 중')
    allrun = run_script('run.mjs', ctx)
    if ctx is not None:
        ctx.tool_call()
    companies = []
    for c in fin['companies']:
        calc = c['calculation']
        companies.append({
            'company': c['company'], 'name': c['name'],
            'years': calc['years'], 'formulas': calc['formulas'],
            'documents': [{k: d.get(k) for k in DOC_FIELDS} for d in c['documents']],
        })
    macro = allrun['macro']
    for ind in macro.get('indicators', []):
        ind.pop('points', None)  # keep first/last/count/missing; full series stays in the source files
    result = {'manifest_digest': fin['manifestDigest'], 'vendor_tree_digest': tree, 'companies': companies,
              'macro': macro, 'limits': allrun.get('limits', []), 'source_mode': allrun.get('sourceMode'),
              'live_fetch': allrun.get('liveFetch')}
    if ctx is not None:
        ctx.store.put_call(key, 'official-corpus', result)
    return result
