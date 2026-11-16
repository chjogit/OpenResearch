"""T2·T3 (PM 2026-11-15): 계정별 엔진 기록 + 초대 코드 가입·동의 + AI 길잡이 사용 한도. 엔진 코드는 바꾸지 않는다.
사용: python patch_t2t3.py <화면 폴더(manage.py 있는 곳)>
- 파일마다 바꿀 자리를 모두 먼저 확인하고, 하나라도 없으면 아무것도 바꾸지 않는다. 이미 적용된 파일(표식 'T2·T3 (PM 2026-11-15)')은 건너뛴다.
- new/ 의 새 파일(accounts/models.py·admin.py·usage.py·migrations)은 그대로 복사한다.
- 되돌리기: before/ 의 파일을 제자리에 덮고, 새 파일을 지운 뒤 manage.py migrate accounts zero (가입 동의·AI 사용량 표만 지워짐)"""
import shutil, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(sys.argv[1]).resolve()
MARK = "T2·T3 (PM 2026-11-15)"
M = MARK

SETTINGS_ADD = f'''

# ── 가입·계정별 기록·AI 사용 한도 ({M}) ─────────
LOGIN_URL = "login"
# True면 근거 리서치·전문가 모드·엔진 창구(/api/)를 로그인한 사람만 씀(배포). PM PC 시연은 False도 가능
MRN_REQUIRE_LOGIN = config("MRN_REQUIRE_LOGIN", default=False, cast=bool)
# 초대 코드(쉼표로 여러 개). 비어 있으면 코드 없이 가입(동의는 항상 필수)
MRN_INVITE_CODES = [c for c in config("MRN_INVITE_CODES", default="", cast=Csv()) if c]
# 지금까지의 엔진 기록(브라우저 쿠키)을 그대로 이어 쓸 아이디(예: PM)
MRN_LEGACY_OWNER_USERS = [c for c in config("MRN_LEGACY_OWNER_USERS", default="", cast=Csv()) if c]
# 계정별 엔진 기록 값을 만들 때 쓰는 비밀 값(비우면 SECRET_KEY). 한번 정하면 바꾸지 않음(바꾸면 계정 기록이 안 보임)
MRN_OWNER_SALT = config("MRN_OWNER_SALT", default="")
# AI 길잡이 한도: 사람마다 하루 호출 수 · 하루 AI 응답 시간(초) · 전체 이번 달 호출 수 (먼저 닿는 쪽에서 멈춤)
AI_DAILY_CALLS = config("AI_DAILY_CALLS", default=30, cast=int)
AI_DAILY_SECONDS = config("AI_DAILY_SECONDS", default=600, cast=int)
AI_MONTHLY_CALLS = config("AI_MONTHLY_CALLS", default=3000, cast=int)
'''

ENV_ADD = f'''
# ── 가입·AI 사용 한도 ({M}) ──
# 배포 서버는 True(로그인한 사람만 근거 리서치·전문가 모드 사용)
MRN_REQUIRE_LOGIN=False
# 초대 코드, 쉼표로 여러 개. 비우면 코드 없이 가입
MRN_INVITE_CODES=
# 지금까지의 기록을 이어 쓸 아이디(예: PM 아이디)
MRN_LEGACY_OWNER_USERS=
# AI 길잡이: 사람마다 하루 30회 · 하루 응답 시간 600초 · 전체 이번 달 3000회
AI_DAILY_CALLS=30
AI_DAILY_SECONDS=600
AI_MONTHLY_CALLS=3000
'''

CONSENT_HTML = '''    {# ''' + M + ''': 초대 코드(설정에 있을 때만) + 동의 #}
    {% if invite_required %}
    <div class="field">
      <label for="invite_code">초대 코드</label>
      <input id="invite_code" name="invite_code" value="{{ form.invite_code.value|default:'' }}" maxlength="40" autocomplete="off" required>
      <p class="field-help">연구용 시연 기간에는 초대받은 분만 가입할 수 있습니다.</p>
    </div>
    {% endif %}
    <div class="field">
      <div class="field-help" style="background:#F3F4FA;border-radius:10px;padding:12px 14px;line-height:1.6">
        <b>이용 안내 (연구용 시연판 · 동의문 v1)</b><br>
        · 연구 목적의 시연 서비스입니다. 투자 권유가 아니며 사거나 팔라는 판단을 드리지 않습니다.<br>
        · 받는 정보는 아이디와 비밀번호(암호화해 저장)뿐입니다. 이메일·이름·전화번호는 받지 않습니다.<br>
        · AI 길잡이를 켜고 질문하면 질문 문장이 AI 회사(Anthropic)로 보내져 처리됩니다. 질문에 개인정보를 적지 마세요.<br>
        · AI 길잡이는 하루 사용량에 한도가 있습니다.<br>
        · 계정 삭제를 요청하시면 계정과 기록을 함께 지웁니다.
      </div>
      <label style="display:flex;gap:8px;align-items:center;margin-top:8px"><input type="checkbox" name="agree" {% if form.agree.value %}checked{% endif %} required> 위 내용을 읽었고 동의합니다</label>
    </div>
'''

GUIDE_LEFT = "const aiLeftText = (u) => `오늘 남은 AI 길잡이 ${u.calls_left}회 · ${Math.floor(u.seconds_left / 60)}분`;   // " + M + "\n"

EDITS = {
    "stocknote/settings.py": [("\nif not DEBUG:\n", SETTINGS_ADD + "\nif not DEBUG:\n")],
    ".env.example": [("# (배포 때만) https 배포 주소.", ENV_ADD.lstrip("\n") + "\n# (배포 때만) https 배포 주소.")],
    "accounts/forms.py": [
        ("from django import forms\n",
         f"import hmac\n\nfrom django import forms\nfrom django.conf import settings\n"),
        ('        fields = ("username",)  # 비밀번호 칸은 부모 폼이 따로 만든다\n',
         '        fields = ("username",)  # 비밀번호 칸은 부모 폼이 따로 만든다\n\n'
         f'    # {M}: 초대 코드(설정에 코드가 있을 때만 필수) + 이용 안내·개인정보 동의(항상 필수)\n'
         '    invite_code = forms.CharField(required=False, max_length=40)\n'
         '    agree = forms.BooleanField(required=True, error_messages={"required": "이용 안내와 개인정보 처리에 동의해 주세요."})\n'),
        ("        return username\n",
         "        return username\n\n"
         "    def clean_invite_code(self):\n"
         "        code = (self.cleaned_data.get(\"invite_code\") or \"\").strip()\n"
         "        codes = invite_codes()\n"
         "        if codes and not any(hmac.compare_digest(code.encode(), c.encode()) for c in codes):\n"
         "            raise forms.ValidationError(\"초대 코드가 맞지 않습니다.\")\n"
         "        return code\n\n\n"
         f"def invite_codes():   # {M}\n"
         "    return [c.strip() for c in getattr(settings, \"MRN_INVITE_CODES\", []) if c and c.strip()]\n"),
    ],
    "accounts/views.py": [
        ("from django.contrib.auth import login, logout\nfrom django.shortcuts import redirect, render\n\nfrom .forms import LoginForm, SignupForm\n",
         "from django.contrib.auth import login, logout\nfrom django.http import JsonResponse\nfrom django.shortcuts import redirect, render\n"
         "from django.utils.http import url_has_allowed_host_and_scheme\n\n"
         "from . import usage\nfrom .forms import LoginForm, SignupForm, invite_codes\nfrom .models import Consent\n\n"
         f"CONSENT_VERSION = \"v1-research\"   # {M}: 동의문 버전(signup.html 「이용 안내」)\n"),
        ("            user = form.save()  # 비밀번호는 해시로 바꿔 저장\n",
         "            user = form.save()  # 비밀번호는 해시로 바꿔 저장\n"
         "            Consent.objects.create(user=user, version=CONSENT_VERSION, invite_code=form.cleaned_data.get(\"invite_code\", \"\"))   # T2 동의 기록\n"),
        ('    return render(request, "accounts/signup.html", {"form": form})\n',
         '    return render(request, "accounts/signup.html", {"form": form, "invite_required": bool(invite_codes())})\n'),
        ("            login(request, form.get_user())  # 세션을 만들어 로그인 상태를 기억함\n            return redirect(\"pages:index\")\n",
         "            login(request, form.get_user())  # 세션을 만들어 로그인 상태를 기억함\n"
         "            nxt = request.GET.get(\"next\", \"\")   # T2: 로그인이 필요한 화면에서 왔으면 그 화면으로 돌려보냄\n"
         "            if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):\n"
         "                return redirect(nxt)\n"
         "            return redirect(\"pages:index\")\n"),
        ('def logout_view(request):\n    if request.method == "POST":\n        logout(request)\n    return redirect("pages:index")\n',
         'def logout_view(request):\n    if request.method == "POST":\n        logout(request)\n    return redirect("pages:index")\n\n\n'
         f"# {M}: 오늘 남은 AI 길잡이 사용량(근거 리서치 화면이 읽음)\n"
         "def ai_usage(request):\n"
         "    return JsonResponse(usage.status(usage.who(request)))\n"),
    ],
    "accounts/urls.py": [
        ('    path("signup/", views.signup_view, name="signup"),   # 회원가입\n',
         '    path("signup/", views.signup_view, name="signup"),   # 회원가입\n'
         f'    path("ai-usage/", views.ai_usage, name="ai_usage"),  # {M}: 오늘 남은 AI 길잡이 사용량\n'),
    ],
    "accounts/templates/accounts/signup.html": [
        ('    <button class="btn btn-v btn-lg auth-submit">회원가입</button>\n',
         CONSENT_HTML + '    <button class="btn btn-v btn-lg auth-submit">회원가입</button>\n'),
    ],
    "accounts/tests.py": [
        ('        return self.client.post(reverse("signup"), {"username": username, "password1": password1, "password2": password2})\n',
         f'        # {M}: 동의 칸이 생겨 함께 보냄\n'
         '        return self.client.post(reverse("signup"), {"username": username, "password1": password1, "password2": password2, "agree": "on"})\n'),
    ],
    "pages/views.py": [
        ("from django.conf import settings\nfrom django.shortcuts import render\n",
         "from django.conf import settings\nfrom django.contrib.auth.views import redirect_to_login\nfrom django.shortcuts import render\n\n\n"
         f"def _login_gate(view):   # {M}: MRN_REQUIRE_LOGIN=True면 로그인한 사람만\n"
         "    def wrapped(request, *a, **kw):\n"
         "        if getattr(settings, \"MRN_REQUIRE_LOGIN\", False) and not request.user.is_authenticated:\n"
         "            return redirect_to_login(request.get_full_path())\n"
         "        return view(request, *a, **kw)\n"
         "    return wrapped\n"),
        ("def research(request):\n", "@_login_gate\ndef research(request):\n"),
        ("def expert_mode(request):\n", "@_login_gate\ndef expert_mode(request):\n"),
    ],
    "pages/engine_proxy.py": [
        ("from django.views.decorators.csrf import csrf_exempt\n",
         "from django.views.decorators.csrf import csrf_exempt\n\n"
         f"import json as _json   # {M}\nimport time as _time\n\nfrom accounts import usage as _usage\n"),
        ("def forward(request, sub):\n",
         "def forward(request, sub):\n"
         f"    if getattr(settings, \"MRN_REQUIRE_LOGIN\", False) and not request.user.is_authenticated:   # {M}\n"
         "        return JsonResponse({\"detail\": \"로그인이 필요해요.\"}, status=401)\n"),
        ('    cookie = "; ".join(f"{k}={request.COOKIES[k]}" for k in ENGINE_COOKIES if k in request.COOKIES)\n',
         "    cookies = {k: request.COOKIES[k] for k in ENGINE_COOKIES if k in request.COOKIES}\n"
         "    owner = _usage.engine_owner(request)   # T2: 로그인한 계정마다 엔진 기록을 나눔\n"
         "    if owner:\n"
         "        cookies[\"mrn_owner\"] = owner\n"
         '    cookie = "; ".join(f"{k}={v}" for k, v in cookies.items())\n'),
        ('    body = request.body if request.method not in ("GET", "HEAD") else None\n',
         '    body = request.body if request.method not in ("GET", "HEAD") else None\n'
         "    ai = _ai_before(request, sub, body)   # T3: AI 길잡이 사용 한도\n"
         "    if ai and ai[\"body\"] is not None:\n"
         "        body = ai[\"body\"]\n"
         "    t0 = _time.monotonic()\n"),
        ('    out = HttpResponse(res.read(), status=res.status,',
         '    raw = res.read()\n'
         '    if ai:\n'
         '        raw = _ai_after(ai, sub, res.status, raw, _time.monotonic() - t0)\n'
         '    out = HttpResponse(raw, status=res.status,'),
        ("            if name in ENGINE_COOKIES:\n",
         "            if name in ENGINE_COOKIES and not (owner and name == \"mrn_owner\"):   # T2: 계정 owner는 화면이 정함\n"),
        ("def expert_page(request):\n",
         "def expert_page(request):\n"
         f"    if getattr(settings, \"MRN_REQUIRE_LOGIN\", False) and not request.user.is_authenticated:   # {M}\n"
         "        return HttpResponse(\"<p style='font:14px sans-serif;padding:24px'>로그인이 필요해요.</p>\", status=401, content_type=\"text/html; charset=utf-8\")\n"),
    ],
    "pages/static/pages/js/pages/research.js": [
        ("const guideOn = () => !!(S.guideAvail && Store.get(KEY('guideOn'), false));\n",
         "const guideOn = () => !!(S.guideAvail && Store.get(KEY('guideOn'), false));\n" + GUIDE_LEFT),
        ("  box.innerHTML = `<div class=\"rs-box ${ai ? 'not' : 'unk'}\">\n",
         "  box.innerHTML = `<div class=\"rs-box ${ai ? 'not' : 'unk'}\">\n"
         "    ${r.ai_limit ? `<p><b>${esc(r.ai_limit.reason)}</b> — AI 없이 규칙으로 찾았어요. 한도가 풀리면 다시 쓸 수 있어요.</p>` : ''}\n"),
        ("  if ($('#g-use')) $('#g-use').onclick = () => { $('#free-q').value = r.rewrite; freeAsk(); };\n",
         "  if ($('#g-use')) $('#g-use').onclick = () => { $('#free-q').value = r.rewrite; freeAsk(); };\n"
         "  if (r.ai_usage && $('#ai-left')) $('#ai-left').textContent = aiLeftText(r.ai_usage);   // T3 남은 양\n"),
        ("  $('#guide-btn').onclick = () => { Store.set(KEY('guideOn'), !on); loadGuide(); };\n",
         "  $('#guide-btn').onclick = () => { Store.set(KEY('guideOn'), !on); loadGuide(); };\n"
         "  if (on) fetch('/accounts/ai-usage/').then((x) => (x.ok ? x.json() : null)).then((u) => {   // T3 남은 양\n"
         "    if (u) el.querySelector('.card > div').insertAdjacentHTML('beforeend', `<p class=\"muted\" id=\"ai-left\" style=\"font-size:13px\">${esc(aiLeftText(u))}</p>`);\n"
         "  }).catch(() => {});\n"),
    ],
}
APPEND_PROXY = f'''


# ── AI 길잡이 사용 한도 ({M}) ─────────────────────────────
# 엔진에서 AI 모델을 부를 수 있는 두 곳(/api/guide/translate, /api/agent/plan)만 본다.
# 한도에 닿았으면 use_model 을 끄고 보내서 엔진이 규칙으로만 찾게 하고, 답에 ai_limit(이유)를 붙인다.
# 한도 안이면 그대로 보내고, 엔진 답을 보고 실제로 AI를 불렀을 때만 사용량을 센다. 답에는 ai_usage(남은 양)를 붙인다.
def _ai_before(request, sub, body):
    if request.method != "POST" or sub not in _usage.AI_PATHS:
        return None
    try:
        data = _json.loads(body or b"{{}}")
    except ValueError:
        return None
    if not isinstance(data, dict) or not _usage.wants_model(sub, data):
        return None
    key = _usage.who(request)
    st = _usage.status(key)
    if st["blocked"]:
        data["use_model"] = False
        return {{"key": key, "blocked": True, "reason": st["reason"], "body": _json.dumps(data, ensure_ascii=False).encode()}}
    return {{"key": key, "blocked": False, "reason": None, "body": None}}


def _ai_after(ai, sub, status, raw, secs):
    try:
        resp = _json.loads(raw)
    except ValueError:
        return raw
    if not isinstance(resp, dict):
        return raw
    if not ai["blocked"] and status < 400 and _usage.model_used(sub, resp):
        _usage.record(ai["key"], secs * 1000)
    st = _usage.status(ai["key"])
    if ai["blocked"]:
        resp["ai_limit"] = {{"blocked": True, "reason": ai["reason"]}}
    resp["ai_usage"] = {{k: st[k] for k in ("calls_left", "seconds_left", "daily_calls", "daily_seconds")}}
    return _json.dumps(resp, ensure_ascii=False).encode()
'''
NEW = ["accounts/models.py", "accounts/admin.py", "accounts/usage.py", "accounts/migrations/__init__.py", "accounts/migrations/0001_initial.py", "accounts/test_t2t3.py"]


def main():
    if not (ROOT / "manage.py").exists():
        sys.exit(f"manage.py 가 없습니다: {ROOT}")
    todo, missing = [], []
    for rel, edits in EDITS.items():
        t = (ROOT / rel).read_text(encoding="utf-8")
        if MARK in t:
            print("이미 적용:", rel); continue
        for old, new in edits:
            if t.count(old) != 1:
                missing.append(f"{rel}: {old[:50]!r} ({t.count(old)}곳)"); continue
            t = t.replace(old, new)
        if rel == "pages/engine_proxy.py":
            t = t.rstrip("\n") + APPEND_PROXY
        todo.append((rel, t))
    if missing:
        sys.exit("바꿀 자리를 못 찾아 아무것도 바꾸지 않았습니다:\n  " + "\n  ".join(missing))
    for rel, t in todo:
        (ROOT / rel).write_text(t, encoding="utf-8", newline="\n"); print("고침:", rel)
    for rel in NEW:
        src = HERE / "new" / rel
        if src.exists():
            (ROOT / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, ROOT / rel); print("새 파일:", rel)
        else:
            print("(없음, 건너뜀):", rel)
    print("완료")


main()
