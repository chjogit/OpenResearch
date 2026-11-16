"""T2·T3 (PM 2026-11-15): 가입 동의 기록과 AI 사용량.

- Consent: 회원가입 때 받은 동의(이용 안내·개인정보·연구용 시연 고지)와 쓴 초대 코드
- AiUsage: AI 길잡이 사용량. 하루·사람(who)마다 한 줄 — 호출 수와 응답에 걸린 시간(ms)
  who = 'u:<회원번호>'(로그인) 또는 'o:<엔진 쿠키 앞부분>'(로그인 없이 쓸 때)
"""
from django.conf import settings
from django.db import models


class Consent(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mrn_consent")
    version = models.CharField("동의문 버전", max_length=20)
    invite_code = models.CharField("쓴 초대 코드", max_length=40, blank=True)
    agreed_at = models.DateTimeField("동의 시각", auto_now_add=True)

    class Meta:
        verbose_name = verbose_name_plural = "가입 동의"

    def __str__(self):
        return f"{self.user} · {self.version}"


class AiUsage(models.Model):
    who = models.CharField("누구", max_length=64, db_index=True)
    day = models.DateField("날짜", db_index=True)
    calls = models.PositiveIntegerField("AI 호출 수", default=0)
    ms = models.PositiveBigIntegerField("AI 응답 시간 합계(ms)", default=0)

    class Meta:
        verbose_name = verbose_name_plural = "AI 사용량"
        constraints = [models.UniqueConstraint(fields=["who", "day"], name="aiusage_who_day")]

    def __str__(self):
        return f"{self.who} {self.day} · {self.calls}회 · {self.ms // 1000}초"
