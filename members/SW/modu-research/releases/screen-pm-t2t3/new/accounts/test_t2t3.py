"""T2·T3 (PM 2026-11-15) 시험: 초대 코드·동의 가입, 계정별 엔진 기록, 로그인 문, AI 길잡이 사용 한도. 실행: python manage.py test accounts
실제 엔진·AI 없이 urlopen을 가짜로 바꿔 「엔진에 무엇을 보내는지·화면에 무엇을 돌려주는지」만 본다."""
import json
from email.message import Message
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from . import usage
from .models import AiUsage, Consent

PW = "ju-sik-note-2026"
ENGINE = "http://127.0.0.1:4395"


class Fake:
    def __init__(self, body, status=200, cookies=()):
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = "application/json"
        for c in cookies:
            self.headers["Set-Cookie"] = c
        self._b = json.dumps(body).encode() if not isinstance(body, bytes) else body

    def read(self):
        return self._b


class SignupT2(TestCase):
    def post(self, **extra):
        data = {"username": "kim", "password1": PW, "password2": PW, **extra}
        return self.client.post(reverse("signup"), data)

    def test_consent_is_required_and_recorded(self):
        self.assertContains(self.post(), "동의해 주세요")
        self.assertFalse(User.objects.exists())
        self.assertRedirects(self.post(agree="on"), reverse("pages:level"))
        c = Consent.objects.get(user__username="kim")
        self.assertEqual(c.version, "v1-research")

    @override_settings(MRN_INVITE_CODES=["MODU-2026", "KIC"])
    def test_invite_code_checked_when_configured(self):
        page = self.client.get(reverse("signup")).content.decode()
        self.assertIn('name="invite_code"', page)
        self.assertContains(self.post(agree="on", invite_code="nope"), "초대 코드가 맞지 않습니다")
        self.assertContains(self.post(agree="on"), "초대 코드가 맞지 않습니다")
        self.assertRedirects(self.post(agree="on", invite_code="KIC"), reverse("pages:level"))
        self.assertEqual(Consent.objects.get(user__username="kim").invite_code, "KIC")

    def test_no_invite_field_without_codes(self):
        self.assertNotIn('name="invite_code"', self.client.get(reverse("signup")).content.decode())

    def test_signup_page_shows_notice(self):
        page = self.client.get(reverse("signup")).content.decode()
        for words in ("연구 목적의 시연", "Anthropic", "이메일·이름·전화번호는 받지 않습니다"):
            self.assertIn(words, page)


@override_settings(MRN_ENGINE_URL=ENGINE)
class OwnerT2(TestCase):
    def setUp(self):
        self.a = User.objects.create_user("a", password=PW)
        self.b = User.objects.create_user("b", password=PW)

    def sent(self, cookies=()):
        with patch("pages.engine_proxy.urlopen", return_value=Fake({"ok": True}, cookies=cookies)) as m:
            res = self.client.get("/api/health")
        return res, m.call_args[0][0].get_header("Cookie") or ""

    def test_each_account_gets_its_own_stable_owner(self):
        self.client.cookies["mrn_owner"] = "browser1"
        self.client.cookies["mrn_csrf"] = "c1"
        self.client.login(username="a", password=PW)
        _, ca1 = self.sent()
        _, ca2 = self.sent()
        self.client.logout(); self.client.login(username="b", password=PW)
        _, cb = self.sent()
        self.assertEqual(ca1, ca2)
        self.assertNotIn("browser1", ca1)
        self.assertNotEqual(ca1, cb)
        self.assertIn("mrn_csrf=c1", ca1)
        self.assertRegex(ca1, r"mrn_owner=[0-9a-f]{32}")

    def test_anonymous_keeps_browser_cookie(self):
        self.client.cookies["mrn_owner"] = "browser1"
        _, c = self.sent()
        self.assertIn("mrn_owner=browser1", c)

    @override_settings(MRN_LEGACY_OWNER_USERS=["a"])
    def test_legacy_user_keeps_old_history(self):
        self.client.cookies["mrn_owner"] = "browser1"
        self.client.login(username="a", password=PW)
        _, c = self.sent()
        self.assertIn("mrn_owner=browser1", c)

    def test_engine_owner_cookie_not_passed_back_for_accounts(self):
        self.client.login(username="a", password=PW)
        res, _ = self.sent(cookies=["mrn_owner=engine-made; Path=/", "mrn_csrf=c9; Path=/"])
        self.assertNotIn("mrn_owner", res.cookies)
        self.assertEqual(res.cookies["mrn_csrf"].value, "c9")


@override_settings(MRN_ENGINE_URL=ENGINE, MRN_REQUIRE_LOGIN=True)
class LoginGateT2(TestCase):
    def test_gate(self):
        r = self.client.get(reverse("pages:research"))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("login"), r["Location"])
        self.assertEqual(self.client.get(reverse("pages:expert_mode")).status_code, 302)
        self.assertEqual(self.client.get("/api/health").status_code, 401)
        self.assertEqual(self.client.get("/engine/expert").status_code, 401)
        self.assertEqual(self.client.get(reverse("pages:learn")).status_code, 200)   # 다른 화면은 열림
        User.objects.create_user("a", password=PW)
        self.client.login(username="a", password=PW)
        self.assertEqual(self.client.get(reverse("pages:research")).status_code, 200)

    def test_login_returns_to_next_but_not_other_sites(self):
        User.objects.create_user("a", password=PW)
        r = self.client.post(reverse("login") + "?next=/research/", {"username": "a", "password": PW})
        self.assertRedirects(r, "/research/", fetch_redirect_response=False)
        self.client.logout()
        r = self.client.post(reverse("login") + "?next=https://evil.example/", {"username": "a", "password": PW})
        self.assertRedirects(r, reverse("pages:index"))


@override_settings(MRN_ENGINE_URL=ENGINE, AI_DAILY_CALLS=2, AI_DAILY_SECONDS=600, AI_MONTHLY_CALLS=100)
class AiLimitT3(TestCase):
    def setUp(self):
        User.objects.create_user("a", password=PW)
        self.client.login(username="a", password=PW)

    def ask(self, engine_answer, path="/api/guide/translate", body=None):
        body = body if body is not None else {"question": "q", "company": "005930", "use_model": True}
        with patch("pages.engine_proxy.urlopen", return_value=Fake(engine_answer)) as m:
            r = self.client.post(path, data=json.dumps(body), content_type="application/json", HTTP_X_CSRF_TOKEN="c")
        return r.json(), json.loads(m.call_args[0][0].data)

    def test_daily_calls_then_rule_only(self):
        ans = {"mode": "model", "model_calls": 1}
        r1, s1 = self.ask(ans)
        r2, _ = self.ask(ans)
        self.assertTrue(s1["use_model"])
        self.assertEqual(r1["ai_usage"]["calls_left"], 1)
        self.assertEqual(r2["ai_usage"]["calls_left"], 0)
        r3, s3 = self.ask({"mode": "rule", "model_calls": 0})
        self.assertFalse(s3["use_model"])                      # 엔진에는 AI 끄고 보냄
        self.assertTrue(r3["ai_limit"]["blocked"])
        self.assertIn("2회", r3["ai_limit"]["reason"])
        self.assertEqual(AiUsage.objects.get().calls, 2)       # 막힌 세 번째는 세지 않음

    def test_failed_or_rule_answers_are_not_counted(self):
        self.ask({"mode": "rule", "model_calls": 0})
        self.ask({"mode": "rule", "model_calls": 0}, body={"question": "q", "use_model": False})
        self.assertFalse(AiUsage.objects.exists())

    def test_seconds_limit(self):
        usage.record("u:%d" % User.objects.get().pk, 600 * 1000)
        r, s = self.ask({"mode": "rule", "model_calls": 0})
        self.assertFalse(s["use_model"])
        self.assertIn("10분", r["ai_limit"]["reason"])

    @override_settings(AI_MONTHLY_CALLS=1)
    def test_monthly_total_across_people(self):
        usage.record("u:999", 100)
        r, s = self.ask({"mode": "rule", "model_calls": 0})
        self.assertFalse(s["use_model"])
        self.assertIn("이번 달", r["ai_limit"]["reason"])

    def test_agent_plan_counts_only_real_model_calls(self):
        self.ask({"model_note": "모델 미설정 (MODU_NODES_LLM_URL / MODU_NODES_LLM_MODEL)"}, "/api/agent/plan", {"question": "q"})
        self.assertFalse(AiUsage.objects.exists())
        self.ask({"model_note": "모델 claude-sonnet-5-5"}, "/api/agent/plan", {"question": "q"})
        self.assertEqual(AiUsage.objects.get().calls, 1)

    def test_other_paths_untouched(self):
        with patch("pages.engine_proxy.urlopen", return_value=Fake({"id": "r1"})) as m:
            r = self.client.post("/api/easy/run", data='{"card": "events"}', content_type="application/json")
        self.assertEqual(m.call_args[0][0].data, b'{"card": "events"}')
        self.assertNotIn("ai_usage", r.json())

    def test_usage_endpoint(self):
        self.ask({"mode": "model", "model_calls": 1})
        u = self.client.get(reverse("ai_usage")).json()
        self.assertEqual((u["calls_today"], u["calls_left"], u["blocked"]), (1, 1, False))
