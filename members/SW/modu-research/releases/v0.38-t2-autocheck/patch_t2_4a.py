"""v0.38 T2-4a 보류 정리 — T2-H1: 명령창 대량 받기(dartdocs fetch)도 앱과 같은 DART 사용량 계측에 올린다 · T2-H2: 「지금 확인」을 뒤에서 돌리고 화면은 상태만 되묻는다.
기존 API 는 그대로(더하기만): POST /api/watch/autocheck/run 은 예전처럼 끝날 때까지 기다리고, ?background=1 을 붙였을 때만 바로 돌아온다. 상태 응답에 checking 칸이 더해진다.
고칠 곳을 먼저 모두 확인하고, 하나라도 못 찾으면 아무것도 바꾸지 않는다. 두 번 돌려도 같다."""
import sys
from pathlib import Path

N = Path(sys.argv[1])
EDITS = {
    'mrn/dartdocs.py': ('def metered_get(', [
        ("def main(argv):\n    import argparse\n    ap = argparse.ArgumentParser(prog='python -m mrn.dartdocs')\n",
         "def metered_get(get=None, log=print, data_dir=None):\n"
         "    \"\"\"v0.38 T2-4(T2-H1) 명령창 대량 받기도 앱과 같은 하루 사용량(dart_usage)에 올리고, 상한에 닿으면 멈춘다.\n"
         "    앱 자료(DB)를 열지 못하거나 쓰는 중이라 잠겨 있으면 세지 않고 받기만 계속한다(받기가 계측 때문에 끊기지 않게).\"\"\"\n"
         "    import sqlite3\n"
         "    get = get or http_get\n"
         "    try:\n"
         "        from . import autocheck as AC\n"
         "        from .store import Store\n"
         "        st = Store(str(data_dir or os.environ.get('MODU_NODES_DATA_DIR') or Path(__file__).resolve().parents[1] / 'data')); AC.ensure(st)\n"
         "        counted = AC.counted_get(st, get)\n"
         "    except Exception as e:\n"
         "        log(f'  (사용량 계측을 열지 못해 세지 않고 받습니다: {type(e).__name__})'); return get\n"
         "    warned = []\n\n"
         "    def g(url, *a, **k):\n"
         "        try:\n"
         "            return counted(url, *a, **k)\n"
         "        except sqlite3.Error as e:                              # 계측 DB 가 잠김 등 — 한 번만 알리고 받기는 계속\n"
         "            if not warned:\n"
         "                warned.append(1); log(f'  (사용량 계측에 쓰지 못한 호출이 있습니다: {type(e).__name__})')\n"
         "            return get(url, *a, **k)\n"
         "    return g\n\n\n"
         "def main(argv):\n    import argparse\n    ap = argparse.ArgumentParser(prog='python -m mrn.dartdocs')\n"),
        ("            n = fetch(cos, kinds, a.start, a.end, limit=a.limit)\n", "            n = fetch(cos, kinds, a.start, a.end, limit=a.limit, get=metered_get())\n"),
    ]),
    'mrn/autocheck.py': ('def check_in_background(', [
        ("def _check(store, trigger, clock, get, env, companies):\n",
         "def check_in_background(store, **kw):\n"
         "    \"\"\"v0.38 T2-4(T2-H2) 「지금 확인」을 뒤에서 돌린다. 바로 돌아오고, 끝났는지는 status()['checking'] 과 마지막 실행 기록으로 본다.\"\"\"\n"
         "    if _RUN_LOCK.locked():\n"
         "        return {'status': 'busy', 'message': '이미 확인하고 있어요. 끝나면 다시 눌러 주세요.'}\n"
         "    th = threading.Thread(target=lambda: check_once(store, 'manual', **kw), name='autocheck-manual', daemon=True); th.start()\n"
         "    return {'status': 'started', 'message': '확인을 시작했어요. 끝나면 목록이 바뀝니다.', 'thread': th}\n\n\n"
         "def _check(store, trigger, clock, get, env, companies):\n"),
        ("    return {'enabled': cfg['enabled'], 'running': running, 'interval_min': cfg['interval_min'],", "    return {'enabled': cfg['enabled'], 'running': running, 'checking': _RUN_LOCK.locked(), 'interval_min': cfg['interval_min'],"),
    ]),
    'mrn/watch_api.py': ('background: int = 0', [
        ("    def autocheck_run(request: Request):\n        r = AC.check_once(store, 'manual')\n",
         "    def autocheck_run(request: Request, background: int = 0):\n"
         "        if background:                                           # v0.38 T2-4(T2-H2): 바로 돌아오고 화면이 상태를 되묻는다\n"
         "            r = AC.check_in_background(store); r.pop('thread', None)\n"
         "            if r.get('status') == 'busy':\n"
         "                raise HTTPException(409, {'code': 'busy', 'message': r['message']})\n"
         "            with store.lock, store.connect() as c:\n"
         "                store.audit(c, owner(request), 'watch.autocheck', 'background', {'status': 'started'})\n"
         "            r['status_label'] = '확인 시작'\n"
         "            return r\n"
         "        r = AC.check_once(store, 'manual')\n"),
    ]),
    'web/watch.js': ("autocheck/run?background=1", [
        ("    try { const r = await api('/api/watch/autocheck/run', {method: 'POST'}); toast(`${r.status_label}: ${r.message || ''}`); }\n    catch(e){ toast(e.message); }\n",
         "    try {                                                            // v0.38 T2-4: 뒤에서 돌리고 2초마다 끝났는지 되묻는다(최대 5분)\n"
         "      await api('/api/watch/autocheck/run?background=1', {method: 'POST'});\n"
         "      let a = null;\n"
         "      for (let i = 0; i < 150; i++) {\n"
         "        await new Promise(r => setTimeout(r, 2000));\n"
         "        a = await api('/api/watch/autocheck');\n"
         "        if (!a.checking) break;\n"
         "        if ($('#wCheck')) $('#wCheck').textContent = `확인하는 중… ${(i + 1) * 2}초`;\n"
         "      }\n"
         "      const lr = a && a.last_run;\n"
         "      toast(a && a.checking ? '아직 확인하고 있어요. 조금 뒤 이 화면을 다시 열어 주세요.' : lr ? `${lr.status_label}: ${lr.message || ''}` : '확인을 마쳤어요.');\n"
         "    }\n    catch(e){ toast(e.message); }\n"),
    ]),
}
todo = {}
for rel, (mark, pairs) in EDITS.items():
    s = (N / rel).read_text(encoding='utf-8')
    if mark in s:
        print(f'{rel}: 이미 적용됨'); continue
    for old, _ in pairs:
        if s.count(old) != 1:
            raise SystemExit(f'{rel}: 「{old[:50]!r}」 자리를 정확히 하나 찾지 못함({s.count(old)}) — 아무것도 바꾸지 않음')
    todo[rel] = (s, pairs)
for rel, (s, pairs) in todo.items():
    for old, new in pairs:
        s = s.replace(old, new)
    (N / rel).write_text(s, encoding='utf-8', newline=''); print(f'{rel}: {len(pairs)}곳 적용')
