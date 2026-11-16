"""관리자 화면(/admin/)에서 가입 동의와 AI 사용량을 볼 수 있게 등록 (PM 2026-11-15, T2·T3)."""
from django.contrib import admin

from .models import AiUsage, Consent


@admin.register(Consent)
class ConsentAdmin(admin.ModelAdmin):
    list_display = ("user", "version", "invite_code", "agreed_at")
    search_fields = ("user__username", "invite_code")


@admin.register(AiUsage)
class AiUsageAdmin(admin.ModelAdmin):
    list_display = ("day", "who", "calls", "ms")
    list_filter = ("day",)
    search_fields = ("who",)
