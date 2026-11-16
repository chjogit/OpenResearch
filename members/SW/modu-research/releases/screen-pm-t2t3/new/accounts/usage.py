"""T2·T3 (PM 2026-11-15): 계정별로 엔진 기록 나누기 + AI 길잡이 사용 한도.

T2 계정별 기록
- 엔진은 「owner 쿠키 값 = 한 사람」으로 실행 기록·가설 일지·내 질문 카드를 나눈다(엔진 코드는 그대로).
- 로그인한 사람은 화면(Django)이 계정마다 고정된 owner 값을 만들어 엔진에 대신 보낸다.
  같은 계정이면 어느 PC·브라우저에서 들어와도 같은 기록, 다른 계정끼리는 섞이지 않는다.
- MRN_LEGACY_OWNER_USERS 에 적힌 아이디(예: PM)는 예전처럼 브라우저 쿠키를 그대로 써서 지금까지의 기록을 이어 본다.

T3 AI 사용 한도 (먼저 닿는 쪽에서 멈춤)
- 사람마다 하루 호출 수(AI_DAILY_CALLS) · 하루 AI 응답 시간 합계(AI_DAILY_SECONDS)
- 모두 합쳐 이번 달 호출 수(AI_MONTHLY_CALLS)
- 한도에 닿으면 AI를 부르지 않고 규칙으로만 찾는다(다른 기능은 그대로). 화면에는 이유와 남은 양을 알려 준다.
"""
import hashlib
import hmac

from django.conf import settings
from django.db.models import F, Sum
from django.utils import timezone

from .models import AiUsage

AI_PATHS = {"guide/translate", "agent/plan"}   # 엔진에서 AI 모델을 부를 수 있는 곳 두 군데


def legacy_users():
    return {x.strip() for x in getattr(settings, "MRN_LEGACY_OWNER_USERS", []) if x and x.strip()}


def engine_owner(request):
    """로그인한 계정의 엔진 owner 값(32자). 로그인하지 않았거나 예전 기록을 잇는 계정이면 None(브라우저 쿠키 그대로)."""
    u = getattr(request, "user", None)
    if not (u and u.is_authenticated):
        return None
    if u.get_username() in legacy_users() and request.COOKIES.get("mrn_owner"):
        return None
    salt = (getattr(settings, "MRN_OWNER_SALT", "") or settings.SECRET_KEY).encode()
    return hmac.new(salt, f"mrn-owner:{u.pk}".encode(), hashlib.sha256).hexdigest()[:32]


def who(request):
    u = getattr(request, "user", None)
    if u and u.is_authenticated:
        return f"u:{u.pk}"
    return "o:" + (request.COOKIES.get("mrn_owner") or "none")[:40]


def status(key):
    d = timezone.localdate()
    row = AiUsage.objects.filter(who=key, day=d).first()
    calls, ms = (row.calls, row.ms) if row else (0, 0)
    month = AiUsage.objects.filter(day__year=d.year, day__month=d.month).aggregate(s=Sum("calls"))["s"] or 0
    lim_c, lim_s, lim_m = settings.AI_DAILY_CALLS, settings.AI_DAILY_SECONDS, settings.AI_MONTHLY_CALLS
    reason = None
    if month >= lim_m:
        reason = "이번 달 전체 AI 사용 한도에 닿았어요"
    elif calls >= lim_c:
        reason = f"오늘 AI 길잡이 {lim_c}회를 다 썼어요"
    elif ms >= lim_s * 1000:
        reason = f"오늘 AI 길잡이 사용 시간 {lim_s // 60}분을 다 썼어요"
    return {"calls_today": calls, "calls_left": max(0, lim_c - calls), "seconds_left": max(0, lim_s - ms // 1000),
            "daily_calls": lim_c, "daily_seconds": lim_s, "month_calls": month, "blocked": reason is not None, "reason": reason}


def record(key, ms):
    obj, _ = AiUsage.objects.get_or_create(who=key, day=timezone.localdate())
    AiUsage.objects.filter(pk=obj.pk).update(calls=F("calls") + 1, ms=F("ms") + max(0, int(ms)))


def wants_model(sub, data):
    if sub == "guide/translate":
        return bool(data.get("use_model"))
    if sub == "agent/plan":
        return data.get("use_model", True) is not False
    return False


def model_used(sub, resp):
    """엔진 답을 보고 실제로 AI 모델을 불렀는지(비용이 생겼는지) 판단."""
    if sub == "guide/translate":
        return (resp.get("model_calls") or 0) > 0
    note = str(resp.get("model_note") or "")
    return note.startswith("모델") and "미설정" not in note
