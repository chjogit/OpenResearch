r"""질의응답 확인용 로컬 서버 (티켓 #53). 명령 하나로 실행:

    cd members\CH
    python -m qa.server            # http://127.0.0.1:8765  (이 PC 에서만 접속, 공개 배포 아님)

- GET  /            시연 HTML 하나(demo/demo.html): 질문 입력 → 해석 → 단계별 실행 추적 → 답·근거·미확보, 성능·구조 탭
- GET  /api/status  {"live": true} — 이 응답이 오면 화면이 '실시간 모드 켜짐'(없으면 저장된 기록 재생)
- POST /api/ask     {"question": "..."} → 줄 단위 JSON(NDJSON) 스트림: 단계마다 {"event":...}, 마지막 {"result":...}
- GET  /api/eval    시험셋 결과(qa/eval_results.json)
DB 는 읽기 전용(ch_agents.db), 비밀값은 .env 에서만 읽고 응답·저장 파일에 넣지 않는다. 한 번에 한 질문만 처리한다.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from qa import agent  # noqa: E402

RUNS = HERE / "_runs"
LOCK = threading.Lock()
STATE: dict = {"llm": None, "universe": None}
SECRET_HINT = ("DATABASE_URL", "API_KEY", "postgres://", "postgresql://", "apikey")


def _llm():
    if STATE["llm"] is None:
        from ch_agents import llm as L

        STATE["llm"] = L.get_llm()
    return STATE["llm"]


def _universe():
    if STATE["universe"] is None:
        STATE["universe"] = agent.load_universe()
    return STATE["universe"]


def scrub(obj):
    """저장·응답 직전 안전장치: 접속 문자열·키처럼 보이는 문자열이 있으면 지운다."""
    s = json.dumps(obj, ensure_ascii=False)
    if any(h.lower() in s.lower() for h in SECRET_HINT):
        raise RuntimeError("응답에 비밀값처럼 보이는 문자열이 있어 중단")
    return obj


class Handler(BaseHTTPRequestHandler):
    server_version = "qa53"

    def log_message(self, fmt, *a):      # 질문 내용을 콘솔에 남기지 않음
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] == "/":
            self._send(200, (HERE.parent / "demo" / "demo.html").read_bytes(), "text/html; charset=utf-8")      # 시연 HTML 하나(#59)
        elif self.path.startswith("/api/status"):
            from ch_agents import llm as L

            from qa import pipeline

            self._send(200, json.dumps({"live": True, "llm": L.MODEL, "pipeline": pipeline.describe(None)}, ensure_ascii=False).encode(), "application/json; charset=utf-8")
        elif self.path.startswith("/api/eval"):
            f = HERE / "eval_results.json"
            self._send(200, f.read_bytes() if f.exists() else b"{}", "application/json; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if self.path != "/api/ask":
            return self._send(404, b"not found", "text/plain")
        try:
            q = str(json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}").get("question") or "").strip()
        except ValueError:
            q = ""
        if not q or len(q) > 400:
            return self._send(400, json.dumps({"error": "질문은 1~400자"}, ensure_ascii=False).encode(), "application/json")
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        def put(o):
            self.wfile.write((json.dumps(scrub(o), ensure_ascii=False, default=str) + "\n").encode())
            self.wfile.flush()

        with LOCK:
            try:
                r = agent.public_view(agent.answer(q, _llm(), emit=lambda e: put({"event": agent.public_view({"trace": [e]})["trace"][0]}), universe=_universe()))
                RUNS.mkdir(exist_ok=True)
                (RUNS / f"{time.strftime('%Y%m%d-%H%M%S')}.json").write_text(json.dumps(scrub(r), ensure_ascii=False, indent=1, default=str), encoding="utf-8")
                r["summary_text"] = agent.summary_text(r)
                print(r["summary_text"], flush=True)
                put({"result": r})
            except Exception as e:  # noqa: BLE001
                put({"error": f"{type(e).__name__}: {str(e)[:200]}"})


def main(port: int = 8765):
    os.environ.setdefault("CH_RAG_HYBRID", "on")      # 시연 서버 기본: 벡터 검색 켜짐(PM 11/5). 끄려면 CH_RAG_HYBRID=off 로 실행. 에이전트 3·4·6 기본값은 그대로(꺼짐)
    for stream in (sys.stdout, sys.stderr):      # Windows 콘솔(cp949)에서 한글·기호 출력이 응답을 끊지 않게
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"질의응답 확인용 서버: http://127.0.0.1:{port}  (종료: Ctrl+C)", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8765)
