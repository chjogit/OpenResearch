"""v0.32 T1 공유용 답 페이지 — 설치 없이 어느 브라우저에서나 열리는 한 장짜리 HTML.

원칙
- 앱의 답(easy.answer)과 근거 확인서(easy.receipt)를 같은 실행에서 만들어 한 파일에 담는다. 새 숫자를 만들지 않는다.
- 외부 요청 없음(글꼴·스크립트·그림을 밖에서 불러오지 않음). 링크는 원문(DART 등) http(s)만.
- 근거 확인서 JSON을 그대로 품는다(<script type="application/json" id="modu-receipt">). 이 파일을 앱의
  「확인서로 다시 계산해 보기」에 넣으면 같은 근거·같은 기준 날짜로 다시 계산해 대조한다.
- 보증 아님·매매 판단 아님 문구, AI 모델 호출 횟수를 함께 적는다.
"""
import hashlib
import html
import json
import re

FORMAT = 'modu-research-share/1'
TIER_CLS = {'fact': 'fact', 'calc': 'calc', 'estimate': 'est'}


def _e(s):
    return html.escape('' if s is None else str(s), quote=True)


def _url(u):
    u = str(u or '')
    return u if re.match(r'^https?://', u) else ''


def _item(it):
    src = it.get('source') or {}
    u = _url(src.get('url'))
    s = (f'<a href="{_e(u)}" target="_blank" rel="noopener noreferrer">{_e(src.get("title") or "원문 열기")}</a>' if u
         else _e(src.get('title') or ''))
    return (f'<li><span class="b {TIER_CLS.get(it.get("tier"), "est")}">{_e(it.get("tier_label"))}</span>'
            f'<div><b>{_e(it.get("label"))}</b><br>{_e(it.get("text"))}'
            + (f'<div class="sm">계산 방법: {_e(it["formula"])}</div>' if it.get('formula') else '')
            + f'<div class="sm">값의 종류: {_e(it.get("kind_label"))}' + (f' · 원문: {s}' if s else '') + '</div></div></li>')


def _table(t):
    def cell(v):
        if isinstance(v, dict) and _url(v.get('url')):
            return f'<a href="{_e(_url(v["url"]))}" target="_blank" rel="noopener noreferrer">{_e(v.get("text") or "링크")}</a>'
        return _e(v if not isinstance(v, dict) else v.get('text'))
    rows = ''.join('<tr>' + ''.join(f'<td>{cell(v)}</td>' for v in r) + '</tr>' for r in t.get('rows', []))
    return (f'<h3>{_e(t.get("title"))}</h3><div class="tw"><table><tr>' + ''.join(f'<th>{_e(c)}</th>' for c in t.get('cols', []))
            + f'</tr>{rows}</table></div>' + (f'<p class="sm">{_e(t["hint"])}</p>' if t.get('hint') else ''))


CSS = """
:root{--ink:#1f2328;--mute:#6b6f76;--line:#e5e1dc;--acc:#d9622b}
*{box-sizing:border-box}body{margin:0;background:#faf8f5;color:var(--ink);font:15px/1.6 -apple-system,"Segoe UI","Malgun Gothic","Apple SD Gothic Neo",sans-serif}
.wrap{max-width:860px;margin:0 auto;padding:24px 18px 48px}
.top{display:flex;align-items:center;gap:10px;flex-wrap:wrap;border-bottom:3px solid var(--acc);padding-bottom:10px}
.brand{font-weight:800;font-size:18px}.tag{background:var(--acc);color:#fff;border-radius:999px;padding:1px 9px;font-size:12px;font-weight:700}
.ro{margin-left:auto;font-size:12.5px;color:var(--mute);border:1px solid var(--line);border-radius:999px;padding:2px 10px;background:#fff}
h1{font-size:21px;margin:18px 0 4px}.q{color:var(--mute)}
.head{font-size:17px;font-weight:700;margin:14px 0 8px}
.cnt span{display:inline-block;margin:0 6px 6px 0}
.b{display:inline-block;border-radius:6px;padding:0 7px;font-size:12px;font-weight:700;white-space:nowrap}
.b.fact{background:#e3f4ea;color:#1d6b3f}.b.calc{background:#e4eefc;color:#2456a6}.b.est{background:#fdeedd;color:#a4510f}.b.unk{background:#eee;color:#555}
ul.it{list-style:none;padding:0;margin:8px 0}ul.it li{display:grid;grid-template-columns:auto 1fr;gap:10px;padding:10px 0;border-bottom:1px solid var(--line)}
.sm{font-size:12.5px;color:var(--mute)}.box{background:#fff;border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin:12px 0}
.box.not{border-left:4px solid #b3412c}.box.unk{border-left:4px solid #888}.box.ok{border-left:4px solid #2f8a6f}
ol.st{padding-left:20px}ol.st li{margin:4px 0}
.tw{overflow-x:auto}table{border-collapse:collapse;font-size:13px;margin:6px 0}td,th{border:1px solid var(--line);padding:4px 7px;text-align:left}th{background:#f3f0ec}
.mono{font-family:ui-monospace,Consolas,monospace;font-size:12px;word-break:break-all}
details{margin:10px 0}summary{cursor:pointer;font-weight:700}
footer{margin-top:26px;font-size:12.5px;color:var(--mute);border-top:1px solid var(--line);padding-top:10px}
@media print{body{background:#fff}.ro{display:none}details{display:block}details>*{display:block}}
"""


def build(ans, rc, question=''):
    """ans = easy.answer(...), rc = easy.receipt(...) (같은 실행). → (html 문자열, 파일 이름용 요약)"""
    if ans.get('run_id') != rc.get('run_id'):
        raise ValueError('답과 확인서가 같은 실행이 아닙니다.')
    q = ans.get('card_title') or question or '직접 한 질문'
    date = (ans.get('cutoff') or '')[:10]
    c = ans.get('count') or {}
    P = ans.get('process') or {}
    rc_json = json.dumps(rc, ensure_ascii=False, sort_keys=True)
    rc_sha = hashlib.sha256(rc_json.encode('utf-8')).hexdigest()
    safe_json = rc_json.replace('</', '<\\/')          # 스크립트 블록이 일찍 닫히지 않게
    key_ids = {(x.get('label'), x.get('text')) for x in ans.get('key') or []}
    rest = [i for i in ans.get('items') or [] if (i.get('label'), i.get('text')) not in key_ids]
    steps = ''.join(f'<li><b>{_e(s.get("title"))}</b> — {_e(s.get("text"))}</li>' for s in P.get('steps') or [])
    srcs = ''.join(f'<tr><td>{_e(s.get("what"))}{"".join("<br><small>" + _e(x) + "</small>" for x in list(s.get("detail") or []) + (["이용 범위: " + s["use"]] if s.get("use") else []))}</td><td class="mono">{_e(s.get("snapshot") or "")}</td><td class="mono">{_e(s.get("sha256") or "")}</td></tr>'
                   for s in ans.get('sources') or [])
    nots = [ans.get('not_this')] + list(ans.get('notices') or []) + list(ans.get('limits') or []) + list(ans.get('source_notes') or [])          # v0.37.9: 하지 않는 것은 모두 보인다(숨기지 않기)
    body = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="generator" content="모두의리서치 · 기업분석 공유 페이지 ({FORMAT})">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:">
<title>{_e(ans.get('name'))} · {_e(q)} — 모두의리서치 · 기업분석</title><style>{CSS}</style></head>
<body><div class="wrap">
<div class="top"><span class="brand">모두의리서치</span><span class="tag">기업분석</span><span class="ro">공유용 읽기 전용 페이지 · 설치 없이 열림</span></div>
<h1>{_e(ans.get('name'))} · {_e(q)}</h1>
<div class="q"><b>{_e(date)} 장 마감까지 공개된 자료 기준</b> · 근거를 확인하고, 판단은 스스로</div>
<div class="head">{_e(ans.get('headline'))}</div>
<div class="cnt"><span class="b fact">자료로 확인 {_e(c.get('fact', 0))}</span><span class="b calc">계산한 값 {_e(c.get('calc', 0))}</span><span class="b est">추정·가정 {_e(c.get('estimate', 0))}</span><span class="b unk">아직 모르는 것 {len(ans.get('unknown') or [])}</span></div>
<ul class="it">{''.join(_item(i) for i in ans.get('key') or []) or '<li><span></span><div>보여 드릴 숫자가 없어요.</div></li>'}</ul>
{f'<details><summary>나머지 숫자 {len(rest)}개</summary><ul class="it">' + ''.join(_item(i) for i in rest) + '</ul></details>' if rest else ''}
<div class="box not"><b>이 결과가 아닌 것</b><ul>{''.join(f'<li>{_e(n)}</li>' for n in nots if n)}</ul></div>
{('<div class="box unk"><b>아직 모르는 것</b><ul>' + ''.join(f'<li>{_e(u.get("text"))}</li>' for u in ans['unknown']) + '</ul></div>') if ans.get('unknown') else ''}
{('<details><summary>자세한 표 ' + str(len(ans['tables'])) + '개</summary>' + ''.join(_table(t) for t in ans['tables']) + '</details>') if ans.get('tables') else ''}
<div class="box"><b>작동 원리 — 이 답이 만들어진 다섯 단계</b><ol class="st">{steps}</ol><p class="sm">{_e(P.get('ai_note'))}</p></div>
{('<details><summary>출처근거 — 쓴 자료와 지문(해시)</summary><div class="tw"><table><tr><th>자료</th><th>사본</th><th>지문(SHA-256)</th></tr>' + srcs + '</table></div><p class="sm">지문은 자료 파일이 한 글자라도 바뀌면 달라져요. 같은 지문이면 같은 자료예요.</p></details>') if srcs else ''}
<div class="box ok"><b>이 답을 직접 확인하는 법</b>
<p>이 파일 안에는 <b>근거 확인서</b>가 함께 들어 있어요. 모두의리서치 앱의 「확인서로 다시 계산해 보기」에 <b>이 파일을 그대로</b> 넣으면, 같은 근거·같은 기준 날짜로 다시 계산해 단계마다 결과 지문을 대조해요.</p>
<p class="sm">확인 번호 <span class="mono">{_e(rc.get('receipt_id'))}</span><br>사슬 지문 <span class="mono">{_e(rc.get('chain_digest'))}</span><br>내장 확인서 지문 <span class="mono">{rc_sha}</span></p></div>
<footer>이 페이지는 모두의리서치 · 기업분석이 규칙과 계산으로 만든 답을 그대로 옮긴 것이에요(AI 모델 호출 {_e(P.get('model_calls', 0))}회).
사거나 팔라는 권유가 아니며, 결과가 옳다거나 투자해도 된다는 보증이 아니에요. 숫자의 출처는 각 줄의 원문 링크와 위 지문으로 확인할 수 있어요.<br>
답 번호 {_e((ans.get('run_id') or '')[:8])} · 형식 {FORMAT}</footer>
</div>
<script type="application/json" id="modu-receipt">{safe_json}</script>
</body></html>"""
    return body, {'name': ans.get('name') or '', 'question': q, 'receipt8': (rc.get('receipt_id') or '')[:8]}


def extract_receipt(text):
    """공유 페이지(HTML)에서 내장 확인서를 꺼낸다. 없으면 None."""
    m = re.search(r'<script type="application/json" id="modu-receipt">(.*?)</script>', text or '', re.S)
    if not m:
        return None
    return json.loads(m.group(1).replace('<\\/', '</'))
