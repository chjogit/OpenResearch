"""#41 시연용 HTML 생성: 에이전트 3·4·6 을 종목 × 확장 켬/끔으로 실제 실행하고(LLM 포함) 결과를 한 파일 HTML 로 만듭니다.

예선 에이전트 코드는 바꾸지 않고 출력(계약 JSON·렌더 결과)만 읽습니다 (specs/demo-page.md D5).

다시 만들기 (members\\CH 에서, 프로젝트 .venv):
    python demo\\build_demo.py run  2026-10-30     # 실행 24회(LLM 포함) → demo\\_cache\\runs.json (이어서 하기 가능)
    python demo\\build_demo.py html 2026-10-30     # 캐시 + 데이터 현황(DB 읽기 전용) → demo\\demo.html
    python demo\\build_demo.py all  2026-10-30     # 위 둘을 차례로
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

TICKERS = (("005930", "삼성전자"), ("000660", "SK하이닉스"), ("005380", "현대차"), ("105560", "KB금융"))
AGENTS = {3: "거시경제", 4: "수급", 6: "투자심리·뉴스"}
LEVELS = ("L1", "L2", "L3")
CACHE = HERE / "_cache" / "runs.json"
OUT = HERE / "demo.html"
MAX_STR = 240          # 근거·문장 등 긴 문자열은 잘라서 기사 전문이 들어가지 않게 함

# 검증 기록 (고정 값): 티켓 Comments 에 기록된 성적표 측정치. 표본 수가 적어 범위가 겹칠 수 있음.
VALIDATION = {
    "note": "8종목 × 에이전트 3·4·6, 기준일 2026-10-30, LLM 포함. 값은 각 티켓 Comments 의 기록이며 반복 2~3회 평균입니다. 표본이 적어 범위가 겹칠 수 있습니다.",
    "rows": [
        {"stage": "분리 전 (에이전트 1·3, 16회)", "removed_total": "8", "range": "-", "note": "기준선. 제거 문장 합계(에이전트 1: 4, 3: 4)"},
        {"stage": "#30 노드 분리 후 (3회)", "removed_total": "41.0", "range": "22~65", "note": "에이전트 3·4·6 합계. 방향 점검 오탐·노드 번호를 근거로 단 문장·에이전트 6 폭주 생성 1건"},
        {"stage": "#32 점검 오탐 정리 (2회)", "removed_total": "29.5", "range": "24~35", "note": "노드 번호 근거 오류 40.7 → 7.0, 완료 유지"},
        {"stage": "#33 부호·표현 보완 (2회)", "removed_total": "-", "range": "-",
         "note": "에이전트 3 제거 9.5 → 6.0 (5~7), 에이전트 6 제거 17.5 → 7.5 (7~8). 에이전트 4 는 재측정하지 않음(합계 없음)"},
    ],
    "meaning": [
        "'제거 문장'은 LLM 이 쓴 문장 중 근거 키 오류·장부 밖 숫자·부호 불일치·금지 표현 등 점검에 걸려 화면에서 빠진 수입니다. 적을수록 좋지만 0 이 목표는 아닙니다(진짜 위반은 걸러져야 함).",
        "점검을 느슨하게 해서 줄인 것이 아닙니다. 진짜 위반(긍정 의도 추정·증권사 목표가·실제 인과 주장·부호가 다른 서술)은 계속 걸리도록 시험으로 고정했습니다.",
        "아직 못 한 것: 에이전트 4 의 #33 이후 재측정, 감성 사전의 개선(평가는 끝났고 정확도 56.6% — 개선 전이라 감성 기반 추론은 계속 건너뜁니다, 상태 SENT_MODEL_UNVALIDATED).",
    ],
}

OVERVIEW = {
    "flow": ["수집 (kic-agent-data)", "DB 배치 (메인·kic-opinion·Object Storage)", "노드 N05~N08·N11·N12", "계약 r4-1.4 (JSON)", "SW 오케스트레이터"],
    "principles": ["숫자는 DB 값만 씁니다 (LLM 은 장부의 키만 인용, 장부 밖 숫자는 제거).", "자료가 없으면 '미확보'로 적고 채워 넣지 않습니다.",
                   "투자 권유·증권사 가격 전망은 쓰지 않습니다 (점검에 걸리면 화면에서 뺍니다).",
                   "20거래일 전망(긍정·중립·부정)은 정해진 규칙이 노드 값만으로 정합니다 (LLM 이 정하지 않음). 매수·매도 판단이나 가격 수준이 아니며, 세 결론의 종합은 오케스트레이터(SW) 담당입니다."],
    "nodes": [("N05·N06", "거시경제(에이전트 3)", "기본/확장"), ("N07·N08", "수급(에이전트 4)", "기본/확장"), ("N11·N12", "투자심리·뉴스(에이전트 6)", "기본/확장")],
}


def _cut(v):
    if isinstance(v, str):
        return v if len(v) <= MAX_STR else v[:MAX_STR] + "…"
    if isinstance(v, list):
        return [_cut(x) for x in v]
    if isinstance(v, dict):
        return {k: _cut(x) for k, x in v.items()}
    return v


def slim_run(out: dict, ticker: str, name: str, agent_no: int, extension: bool) -> dict:
    """run_node_agent 결과 → 페이지에 넣을 만큼만 (원문 attempts·prompt 는 빼고 개수만)."""
    from ch_agents import renderer

    c = out["contract"]
    keep = ("agent", "target", "asOf", "status", "summary", "claims", "upsideFactors", "downsideRisks", "unverified", "nextChecks",
            "evidence", "nodes", "nodeSummary", "predictionSkippedReason", "conflicts", "dataQuality", "disclaimer", "reportId", "schemaVersion")
    rendered = renderer.render_all(c)
    return {
        "ticker": ticker, "name": name, "agentNo": agent_no, "agentName": AGENTS[agent_no], "ext": bool(extension),
        "status": out["status"], "seconds": out["seconds"], "attempts": len(out["attempts"]),
        "removed": len(out.get("removed") or []), "claims": len(c.get("claims") or []),
        "contract": _cut({k: c[k] for k in keep if k in c}),
        "render": {lv: _cut(rendered[f"{lv}-defensive"]["markdown"]) for lv in LEVELS},
    }


def run_one(as_of: str, ticker: str, name: str, agent_no: int, extension: bool) -> dict:
    from ch_agents import llm

    t0 = time.monotonic()
    out = llm.run_node_agent(agent_no, ticker, as_of=as_of, extension=extension)
    r = slim_run(out, ticker, name, agent_no, extension)
    r["wall_seconds"] = round(time.monotonic() - t0, 1)
    return r


def key_of(ticker: str, agent_no: int, ext: bool) -> str:
    return f"{ticker}|{agent_no}|{int(ext)}"


def collect_runs(as_of: str, workers: int = 4, cache: Path = CACHE, runner=run_one) -> dict:
    """24회 실행. 이미 캐시에 있는 조합은 건너뜀(중단 후 이어서 하기). 기준일이 다르면 캐시를 버림."""
    data = {"as_of": as_of, "runs": {}}
    if cache.exists():
        old = json.loads(cache.read_text(encoding="utf-8"))
        if old.get("as_of") == as_of:
            data = old
    todo = [(t, n, a, e) for t, n in TICKERS for a in AGENTS for e in (False, True) if key_of(t, a, e) not in data["runs"]]
    cache.parent.mkdir(parents=True, exist_ok=True)

    def work(job):
        t, n, a, e = job
        return key_of(t, a, e), runner(as_of, t, n, a, e)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for k, r in ex.map(work, todo):
            data["runs"][k] = r
            cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data

OPINION_SOURCES = ("naver_blog", "naver_cafe", "youtube_comment")      # 개인 작성 글 (11/3 사용자·PM 결정: 내용 비노출)
HIDDEN = "개인 작성 글 (블로그·카페·유튜브 댓글 — 내용 비공개)"


def doc_sources(ids: list[int]) -> dict[int, str]:
    """충돌 구역 인용이 가리키는 문서(doc_id)의 출처를 메인·kic-opinion 에서 읽기 전용으로 찾음. 못 찾으면 키가 없음."""
    import psycopg
    from dotenv import load_dotenv

    load_dotenv()
    out: dict[int, str] = {}
    for env in ("DATABASE_URL", "OPINION_DATABASE_URL"):
        url = os.getenv(env, "")
        if not url or not ids:
            continue
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("SET default_transaction_read_only = on")
            out.update({int(i): s for i, s in conn.execute("SELECT doc_id, source FROM rag.document WHERE doc_id = ANY(%s)", [list(ids)]).fetchall()})
    return out


def conflict_doc_ids(runs: dict) -> list[int]:
    ids = set()
    for r in runs["runs"].values():
        for cf in r["contract"].get("conflicts") or []:
            for v in cf.get("views") or []:
                ids.update(int(x.split(":")[1]) for x in v.get("evidenceLinks") or [] if str(x).startswith("doc:") and x.split(":")[1].isdigit())
    return sorted(ids)


def _stem(label: str) -> str:
    return (label or "").rstrip(".… ").strip()


def mask_opinion(runs: dict, source_of: dict[int, str]) -> tuple[dict, list[str]]:
    """블로그·카페 글 내용·링크를 가림(사용자 결정 11/3). 출처·발행일·근거 ID 는 남겨 근거 연결은 보이게 함.
    충돌 구역 문장은 인용 문서가 블로그·카페이거나 출처를 못 찾으면 가림(뉴스·유튜브는 그대로). 가린 글 조각 목록(누출 검사용)을 함께 돌려줌."""
    out = json.loads(json.dumps(runs))
    snippets: list[str] = []
    for r in out["runs"].values():
        c = r["contract"]
        for e in c.get("evidence") or []:
            if e.get("source") in OPINION_SOURCES:
                if _stem(e.get("label")) and _stem(e["label"]) != HIDDEN:
                    snippets.append(_stem(e["label"]))
                e["label"], e["url"], e["note"] = HIDDEN, None, None
        for cf in c.get("conflicts") or []:
            for v in cf.get("views") or []:
                links = [int(x.split(":")[1]) for x in v.get("evidenceLinks") or [] if str(x).startswith("doc:") and x.split(":")[1].isdigit()]
                if any(source_of.get(i) in OPINION_SOURCES or i not in source_of for i in links):
                    head, sep, body = v["text"].partition(": ")
                    if sep and body.strip() and body.strip() != HIDDEN:
                        snippets.append(body.strip().rstrip(".… "))
                    v["text"] = f"{head}{sep}{HIDDEN}" if sep else HIDDEN
    text = json.dumps(out, ensure_ascii=False)
    uniq = sorted({sn for sn in snippets if len(sn) >= 12}, key=len, reverse=True)
    for sn in uniq:                       # 다른 문장 안에 같은 조각이 남아 있으면 그것도 가림
        text = text.replace(sn, HIDDEN)
    return json.loads(text), uniq


def opinion_leaks(html: str, snippets: list[str]) -> list[str]:
    """저장 전 검사: 블로그·카페 주소와 가린 글 조각이 HTML 에 남아 있으면 그 목록."""
    hits = [h for h in ("blog.naver.com", "cafe.naver.com", "youtube.com", "youtu.be") if h in html]
    hits += [f"글 조각: {sn[:20]}…" for sn in snippets if sn in html]
    return hits


# 미확보 항목: 내부 키 대신 한국어 이름 + 이유 (PM 결정 11/3). 대응표에 없는 키가 화면에 나오면 저장 거부.
MISSING_KO = {
    "scenario_assumptions": "시나리오 가정값(사용자 입력 없음 — 기본 환산만 표시)",
    "price_after_event": "사건 이후 주가(기준일 이후라 아직 없음 — 미래 자료 사용 금지)",
    "호가 잔량": "호가 잔량(공개 원천 없음)",
    "세부 주체(금융투자·투신·연기금)": "세부 투자자(금융투자·투신·연기금) 자료(공개 원천 없음)",
}
RAW_KEY = re.compile(r"(?<![A-Za-z0-9_])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![A-Za-z0-9_])")
TARGET_PRICE = re.compile(r"목표\s*주가|목표가")
TP_MASK = "[증권사 가격 전망]"


def _short(ko: str) -> str:
    return ko.split("(")[0].strip()


def _visible_strings(c: dict):
    """화면에 글자로 나오는 계약 필드(내부 키 점검 대상)."""
    for n in c.get("nodes") or []:
        yield n.get("reason") or ""
        yield from n.get("missingInputs") or []
    for u in c.get("unverified") or []:
        yield u.get("item") or ""
        yield u.get("reason") or ""
    for cl in c.get("claims") or []:
        yield cl.get("text") or ""
    yield c.get("predictionSkippedReason") or ""
    for x in c.get("nextChecks") or []:
        yield x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)


def localize_missing(runs: dict) -> dict:
    out = json.loads(json.dumps(runs))
    for r in out["runs"].values():
        c = r["contract"]
        for n in c.get("nodes") or []:
            n["missingInputs"] = [MISSING_KO.get(m, m) for m in n.get("missingInputs") or []]
            if n.get("reason"):
                n["reason"] = _replace_keys(n["reason"])
        for u in c.get("unverified") or []:
            for f in ("item", "reason"):
                if u.get(f):
                    u[f] = _replace_keys(u[f])
        c["nextChecks"] = [_replace_keys(x) if isinstance(x, str) else x for x in c.get("nextChecks") or []]
    return out


def _replace_keys(text: str) -> str:
    for k, ko in MISSING_KO.items():
        text = text.replace(k, _short(ko) if k.isascii() else k)
    return text


def raw_key_hits(runs: dict) -> list[str]:
    """한국어 대응표에 없는 내부 키(snake_case)가 화면 문자열에 남았는지."""
    hits = set()
    for r in runs["runs"].values():
        for t in _visible_strings(r["contract"]):
            hits.update(RAW_KEY.findall(t))
        for md in r["render"].values():
            hits.update(RAW_KEY.findall(md))
    return sorted(hits)


def mask_target_price(runs: dict) -> dict:
    """기사 제목 인용 속 '목표주가'를 '[증권사 가격 전망]'으로 (충돌 구역 문장·근거 라벨·노트). 면책 문구 등 시스템 문장은 그대로."""
    out = json.loads(json.dumps(runs))
    for r in out["runs"].values():
        c = r["contract"]
        for e in c.get("evidence") or []:
            for f in ("label", "display", "note"):
                if isinstance(e.get(f), str):
                    e[f] = TARGET_PRICE.sub(TP_MASK, e[f])
        for cf in c.get("conflicts") or []:
            for v in cf.get("views") or []:
                v["text"] = TARGET_PRICE.sub(TP_MASK, v["text"])
    return out


# ---- #48 표시 정리: 내부 코드를 한국어로, 충돌을 카드로, 처리 통계를 미확보에서 분리 (시연 렌더러만, 에이전트 출력은 그대로)
NODE_KO = {"N05": "거시 데이터 점검", "N06": "거시 해석", "N07": "수급 데이터 점검", "N08": "수급 해석",
           "N11": "심리·뉴스 데이터 점검", "N12": "심리·뉴스 해석"}
PHRASE_KO = (("확장 노드 입력 요건 미충족", "추가 분석에 필요한 자료 부족"), ("D1 사후 탐색 등급", "사후 탐색 단계(검증 전)"),
             ("CAR", "사건 뒤 주가 반응(초과수익)"))
TAG_KO = {"Fact": "사실", "Computation": "계산", "Prediction": "예측", "Interpretation": "해석"}
KEEP_KEYS = {"nodeId", "claimId", "evidenceIds", "evidenceId", "evidenceLinks", "id", "reportId", "ticker", "agent", "schemaVersion", "tag"}
STAT_RE = re.compile(r"문서 \d+건")


_L, _R = r"(?<![A-Za-z0-9_])", r"(?![A-Za-z0-9_])"   # 한글 조사('E10에서')가 붙어도 코드 경계로 인식 ( 는 한글을 단어 문자로 봄)


def ko_text(t: str) -> str:
    """내부 코드(N05 등)·약어(CAR)·사건/근거 번호를 사람이 읽는 말로. 원 코드는 화면의 title 이나 표 ID 칸에만 남음."""
    for a, b in PHRASE_KO:
        t = re.sub(rf"{_L}{re.escape(a)}{_R}" if a.isascii() else re.escape(a), b, t)
    t = re.sub(rf"{_L}N(05|06|07|08|11|12){_R}", lambda m: NODE_KO[f"N{m.group(1)}"], t)
    t = re.sub(rf"사건 E0*\d+(?:\s*(?:[·,、]|과|와)\s*E0*\d+)*", lambda m: "사건 " + re.sub(r"E0*(\d+)", r"\1", m.group(0)[3:]), t)   # '사건 E6·E7' → '사건 6·7'
    t = re.sub(r"근거 E0*(\d+)", r"근거 \1", t)
    return re.sub(rf"{_L}E0*(\d+){_R}", r"근거 \1", t)


def _ko_all(v, key=None):
    if isinstance(v, str):
        return v if key in KEEP_KEYS else ko_text(v)
    if isinstance(v, list):
        return [_ko_all(x, key) for x in v]
    if isinstance(v, dict):
        return {k: _ko_all(x, k) for k, x in v.items()}
    return v


def split_stat(item: str) -> tuple[str, list[str]]:
    """'…문서 0건, …문서 43건' 같은 처리 통계 문장을 (빠진 자료 문구, 처리 기록 조각) 으로. 0건 조각은 버림."""
    if not STAT_RE.search(item):
        return item, []
    return "", [c.strip() for c in item.split(",") if STAT_RE.search(c) and not re.search(r"(?<!\d)0건", c)]


def conflict_card(cf: dict) -> dict:
    views = []
    for v in cf.get("views") or []:
        head, sep, body = (v.get("text") or "").partition(": ")
        docs = [x.split(":")[1] for x in v.get("evidenceLinks") or [] if str(x).startswith("doc:")]
        views.append({"head": head if sep else "", "text": body if sep else head, "tagKo": TAG_KO.get(v.get("tag"), v.get("tag") or ""), "docs": docs})
    card = {"topic": cf.get("topic") or "", "node": cf.get("nodeId") or "", "views": views, "summary": None}
    if views and all(HIDDEN in v["text"] for v in views):
        n = lambda w: sum(len(v["docs"]) or 1 for v in views if v["head"].startswith(w))   # noqa: E731
        alldocs = sorted({d for v in views for d in v["docs"]})
        card["summary"] = (f"개인 작성 글 사이 논조가 갈림 — 긍정 {n('긍정')}건·부정 {n('부정')}건"
                           f"(내용 비공개, 근거 문서 {', '.join(alldocs) or '-'})")
        card["views"] = []
    return card


def localize(runs: dict) -> dict:
    """#48: 저장된 결과를 화면용으로 정리한 사본. 충돌은 카드, 처리 통계는 '처리 기록', 내부 코드는 한국어."""
    out = json.loads(json.dumps(runs))
    for r in out["runs"].values():
        c = r["contract"]
        proc: list[str] = []
        un = []
        for u in c.get("unverified") or []:
            item = u.get("item", "") if isinstance(u, dict) else str(u)
            rest, st = split_stat(item)
            proc += st
            if not rest:
                continue
            un.append(u)
        c["unverified"], c["processing"] = un, proc
        for n in c.get("nodes") or []:
            keep = []
            for m in n.get("missingInputs") or []:
                rest, st = split_stat(m)
                proc += st
                if rest:
                    keep.append(rest)
            n["missingInputs"] = keep
        c["processing"] = list(dict.fromkeys(c["processing"]))
        c["conflicts"] = [conflict_card(cf) for cf in c.get("conflicts") or []]
        r["contract"] = _ko_all(c)
        r["render"] = {lv: ko_text(t) for lv, t in r["render"].items()}
    return out


JSON_RE = re.compile(r'^\s*[\[{]\s*"')
RAW_CODE_RE = re.compile(rf"{_L}N(05|06|07|08|11|12){_R}|{_L}CAR{_R}|{_L}D1 사후|확장 노드 입력 요건 미충족|{_L}E\d+{_R}")


def display_hits(runs: dict) -> list[str]:
    """저장 전 검사(#48): 화면 문자열에 JSON 원문·날것의 내부 코드·0건 미확보 항목이 남았는지. 식별자 칸(KEEP_KEYS)은 제외."""
    hits: list[str] = []

    def walk(v, key=None):
        if isinstance(v, str):
            if key in KEEP_KEYS:
                return
            if JSON_RE.match(v):
                hits.append(f"JSON 원문: {v[:30]}")
            if RAW_CODE_RE.search(v):
                hits.append(f"내부 코드: {RAW_CODE_RE.search(v).group(0)}")
        elif isinstance(v, list):
            for x in v:
                walk(x, key)
        elif isinstance(v, dict):
            for k, x in v.items():
                walk(x, k)

    for r in runs["runs"].values():
        c = r["contract"]
        walk({k: c.get(k) for k in ("summary", "claims", "unverified", "processing", "conflicts", "nodes", "upsideFactors", "downsideRisks", "nextChecks", "predictionSkippedReason")})
        walk(r["render"])
        for u in c.get("unverified") or []:
            if re.search(r"(?<!\d)0건", str(u.get("item", "") if isinstance(u, dict) else u)):
                hits.append(f"0건 미확보 항목: {str(u)[:40]}")
    return list(dict.fromkeys(hits))


STATUS_SQL = {
    "docs": "SELECT source, count(*) AS n, min(published_at)::date AS first, max(published_at)::date AS last FROM rag.document GROUP BY source ORDER BY n DESC",
    "size": "SELECT round(pg_database_size(current_database()) / 1048576.0)::int AS mb",
}
TABLES = (("core.price_daily", "일별 시세"), ("core.investor_flow_daily", "투자자별 수급"), ("core.stock_lending_daily", "대차잔고"),
          ("core.financial_fact", "재무제표 계정"), ("core.disclosure", "공시 목록"), ("rag.chunk", "공시·기사 청크"),
          ("core.macro_obs", "거시 지표 관측치"), ("core.ownership_report", "대량보유상황보고(신규)"), ("core.largest_holder", "최대주주 지분(신규)"),
          ("core.audit_opinion", "감사의견(신규)"), ("core.credit_balance", "신용공여 잔고: 시장 전체 일별(신규)"), ("core.financial_item", "재무 항목: 감가상각·이자비용 등(신규)"))
SOURCE_KO = {"naver_news": "뉴스(국내)", "finnhub_news": "뉴스(해외)", "naver_news_backfill": "뉴스(과거 보강)", "dart_report": "공시 보고서",
             "youtube_comment": "유튜브 댓글", "naver_blog": "블로그", "naver_cafe": "카페"}
UNAVAILABLE = [
    "호가 잔량·세부 투자자(금융투자·투신·연기금) 자료 — 수급 노드가 '미확보'로 표시",
    "감성 사전의 개선 — 사람 라벨 600건 평가 결과 정확도 56.6%(긍정 과소 탐지·중립 편향), 개선 전이라 감성 기반 추론은 건너뜀",
    "공시 주석표 속 감가상각·이자 등 일부 재무 항목 — 계정 매핑 보강은 본선 후보",
]


def collect_status() -> dict:
    """데이터 현황: 메인·kic-opinion 을 읽기 전용으로 집계. 접속 정보는 결과에 넣지 않음."""
    import psycopg
    from dotenv import load_dotenv

    load_dotenv()
    out: dict = {"main": {}, "opinion": {}, "tables": [], "unavailable": UNAVAILABLE}
    for key, env in (("main", "DATABASE_URL"), ("opinion", "OPINION_DATABASE_URL")):
        url = os.getenv(env, "")
        if not url:
            out[key] = {"error": "접속 설정 없음"}
            continue
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("SET default_transaction_read_only = on")
            conn.execute("SET statement_timeout = '60s'")
            docs = conn.execute(STATUS_SQL["docs"]).fetchall()
            out[key] = {"mb": conn.execute(STATUS_SQL["size"]).fetchone()[0],
                        "docs": [{"source": SOURCE_KO.get(s, s), "n": n, "first": str(a), "last": str(b)} for s, n, a, b in docs]}
            if key == "main":
                for tbl, label in TABLES:
                    try:
                        n = conn.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]
                    except Exception as e:  # noqa: BLE001  아직 적용 전인 표 등
                        n, _ = None, e
                    out["tables"].append({"table": tbl, "label": label, "n": n})
    out["limits"] = {"main_mb": 800, "retention_days": 14}
    out["market"] = collect_market()
    return out


def collect_market() -> list[dict]:
    """시장 지표(시장 전체 일별): 신용공여 잔고의 행 수·기간·최신 기준일. 접속 정보는 넣지 않음."""
    import psycopg
    from dotenv import load_dotenv

    load_dotenv()
    url = os.getenv("DATABASE_URL", "")
    if not url:
        return []
    try:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("SET default_transaction_read_only = on")
            n, a, b = conn.execute("SELECT count(*), min(bas_dt), max(bas_dt) FROM core.credit_balance").fetchone()
        return [{"label": "신용공여 잔고 (시장 전체, 일별, 원)", "n": n, "first": str(a), "last": str(b)}]
    except Exception:  # noqa: BLE001  표가 아직 없으면 비움
        return []


def git_head() -> str:
    import subprocess

    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=HERE, capture_output=True, text=True, timeout=10).stdout.strip() or "-"
    except Exception:  # noqa: BLE001
        return "-"


def load_sentiment_eval() -> dict:
    return json.loads((HERE / "sentiment_eval.json").read_text(encoding="utf-8"))


def kst_now() -> str:
    return datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST")


OUTLOOK_NOTE = ("전망은 정해진 규칙(outlook-r1)이 노드 값만으로 계산한 20거래일 가격 방향입니다. 저장한 LLM 실행 결과는 그대로 두고 전망만 기준일에 맞춰 다시 계산했습니다 "
                "(에이전트 6 은 원문 14일 보관이라 당시와 다를 수 있음). 세 결론의 종합은 오케스트레이터(SW) 담당이며 여기서는 만들지 않습니다.")


def outlook_builder(as_of: str, ticker: str, agent_no: int) -> dict:
    """노드만 실행해(LLM 없음) 전망 계산 결과를 얻는다."""
    from ch_agents import db, node_agents

    return node_agents.build_data(agent_no, ticker, as_of, extension=False, co=db.company(ticker)).extra["outlook"]


def collect_outlook(as_of: str, builder=outlook_builder) -> dict:
    """{ticker: {agent: 계약 outlook 블록}}. 화면에 나가기 전 금지 표현 검사(outlook.problems)를 통과해야 한다."""
    from ch_agents import contract, outlook

    out: dict = {}
    for t, _ in TICKERS:
        out[t] = {}
        for no in AGENTS:
            blk = contract.outlook_block(builder(as_of, t, no), {})
            texts = [f["text"] for f in blk["positiveFactors"] + blk["negativeFactors"]] + [x["text"] for x in blk["signals"]] + [blk["limit"], blk["note"]]
            bad = outlook.problems(" ".join(texts))
            if bad:
                raise ValueError(f"전망 문장에 금지 표현 {bad} ({t} 에이전트 {no})")
            out[t][str(no)] = blk
    return out


def load_outlook_validation() -> dict:
    """#55 적중률 결과(hit_rate.json)의 요약. 파일이 없으면 '측정 중'."""
    from ch_agents import outlook

    p = HERE.parent / "outlook" / "hit_rate.json"
    if not p.exists():
        return {"status": "none", "note": "적중률 측정 중 (결과 파일 없음)"}
    d = json.loads(p.read_text(encoding="utf-8"))
    rows = []
    for no, name in AGENTS.items():
        e = (d.get("agents") or {}).get(str(no)) or {}
        if "unverified" in e:
            rows.append({"agent": no, "name": name, "unverified": e["unverified"], "verdictLabel": e.get("verdictLabel"), "notice": outlook.VERDICT_NOTICE["unverified"]})
            continue
        non = e.get("nonOverlapping") or {}
        rows.append({"agent": no, "name": name, "rate": e.get("rate"), "n": e.get("n"), "ci95": e.get("ci95"), "neutralShare": non.get("neutralShare"),
                     "baselines": {k: v.get("rate") for k, v in (non.get("baselines") or {}).items()}, "period": e.get("period"),
                     "verdict": e.get("verdict"), "verdictLabel": e.get("verdictLabel"), "notice": outlook.VERDICT_NOTICE.get(e.get("verdict"))})
    return {"status": "measured", "ruleVersion": d.get("ruleVersion"), "basis": d.get("basis"), "generatedAt": d.get("generatedAt"), "rows": rows,
            "doc": "docs/OUTLOOK_BACKTEST.md", "command": d.get("command"),
            "limits": ["겹치지 않는 20거래일 간격 표본이 헤드라인이며, 같은 날짜의 종목은 시장 움직임을 공유해 신뢰구간은 실제보다 좁습니다.",
                       "에이전트 3: 지표 수정 이력 미보관(공표 시점 규칙으로 보수 처리), 판정이 드물어 건수가 적습니다. 에이전트 4: 실제 서비스의 수급 하루 지연은 반영하지 않았습니다.",
                       "에이전트 6: 원문 보관 14일이라 과거 재계산 불가 — 앞으로 기록해 사후 측정합니다."]}


def build_payload(runs: dict, status: dict, generated_at: str | None = None, outlook: dict | None = None) -> dict:
    rs = runs["runs"]
    return {
        "meta": {"asOf": runs["as_of"], "generatedAt": generated_at or kst_now(), "runs": len(rs),
                 "llmCalls": sum(r["attempts"] for r in rs.values()), "contract": "r4-1.4", "commit": git_head(), "outlookNote": OUTLOOK_NOTE},
        "tickers": [{"ticker": t, "name": n} for t, n in TICKERS], "agents": {str(k): v for k, v in AGENTS.items()},
        "runs": rs, "status": status, "validation": VALIDATION, "sentimentEval": load_sentiment_eval(), "overview": OVERVIEW,
        "outlook": outlook or {}, "outlookValidation": load_outlook_validation(),
    }


FORBIDDEN = (re.compile(r"postgres(ql)?://", re.I), re.compile(r"\bsk-[A-Za-z0-9]{16,}"), re.compile(r"api[_-]?key\s*[=:]", re.I),
             re.compile(r"AWS_(ACCESS|SECRET)", re.I), re.compile(r"neon\.tech", re.I), re.compile(r"목표\s*주가\s*는?\s*\d"))


def forbidden_hits(html: str, secrets: list[str] | None = None) -> list[str]:
    """비밀값·DB 주소·권유 표현 검색. secrets: 실제 환경 값(8자 이상)이 그대로 들어 있으면 잡음."""
    hits = [p.pattern for p in FORBIDDEN if p.search(html)]
    hits += [f"환경 값 포함({i})" for i, s in enumerate(secrets or []) if len(s) >= 8 and s in html]
    return hits


def build_html(payload: dict) -> str:
    tpl = (HERE / "template.html").read_text(encoding="utf-8")
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return tpl.replace("/*__DATA__*/null", blob, 1)


def env_secrets() -> list[str]:
    from dotenv import load_dotenv

    load_dotenv()
    names = ("DATABASE_URL", "OPINION_DATABASE_URL", "UPSTAGE_API_KEY", "ECOS_API_KEY", "COHERE_API_KEY", "DART_API_KEY",
             "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_ENDPOINT_URL_S3")
    return [os.environ[n] for n in names if os.environ.get(n)]


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] not in ("run", "html", "all"):
        print(__doc__)
        return 2
    cmd, as_of = argv[0], argv[1]
    if cmd in ("run", "all"):
        runs = collect_runs(as_of)
        print(f"실행 {len(runs['runs'])}건, LLM 호출 {sum(r['attempts'] for r in runs['runs'].values())}회")
    if cmd in ("html", "all"):
        runs = json.loads(CACHE.read_text(encoding="utf-8"))
        if runs.get("as_of") != as_of or len(runs["runs"]) < len(TICKERS) * len(AGENTS) * 2:
            print("캐시가 기준일과 다르거나 덜 찼습니다. run 먼저 실행하세요.")
            return 1
        runs, snippets = mask_opinion(runs, doc_sources(conflict_doc_ids(runs)))
        runs = localize(runs)
        runs = mask_target_price(localize_missing(runs))
        keys = raw_key_hits(runs)
        if keys:
            print("한국어 대응표에 없는 내부 키가 화면에 남음, 저장하지 않음:", keys)
            return 1
        shown = display_hits(runs)
        if shown:
            print("화면 표시 검사 실패(JSON 원문·내부 코드·0건 항목), 저장하지 않음:", shown[:10])
            return 1
        html = build_html(build_payload(runs, collect_status(), outlook=collect_outlook(as_of)))
        bad = forbidden_hits(html, env_secrets()) + opinion_leaks(html, snippets)
        if bad:
            print("금지 패턴 발견, 저장하지 않음:", bad)
            return 1
        OUT.write_text(html, encoding="utf-8")
        print(f"저장: {OUT} ({len(html) // 1024} KB), 가린 블로그·카페 글 조각 {len(snippets)}개")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
