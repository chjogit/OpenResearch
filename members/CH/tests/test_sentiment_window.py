"""#76: 감성 변화 비교 창 = 최근 7일 vs 직전 7일(8~14일). 보관 기간(14일)에 맞춰 영원히 안 차는 구조를 없앤다."""
from __future__ import annotations

from ch_agents import agent3_sentiment_flow as s3
from conftest import CO
from test_compute import AS_OF, _sent_bundle

LABEL = "블로그 감성 변화(최근 7일 − 직전 7일)"


def _blog(days_recent, days_prior, n_prior=6, extra=()):
    rows = [{"d": d, "source": "naver_blog", "n": 3, "score": 0.4} for d in days_recent]
    rows += [{"d": d, "source": "naver_blog", "n": n_prior, "score": 0.1} for d in days_prior]
    return rows + list(extra)


RECENT = ["2026-10-25", "2026-10-24", "2026-10-23", "2026-10-22"]                  # 최근 7일 (AS_OF=2026-10-25)
PRIOR5 = ["2026-10-18", "2026-10-17", "2026-10-16", "2026-10-15", "2026-10-14"]     # 직전 7일(10-12~10-18) 중 5일


def _facts(docs):
    b = _sent_bundle()
    b["docs"] = [r for r in b["docs"] if r["source"] != "naver_blog"] + docs
    f = s3.compute(b, CO, AS_OF)["facts"]
    return f, {g["label"]: g["reason"] for g in f.gaps}


def test_blog_change_is_computed_from_prior_7_days_with_5_days_and_20_docs():
    f, gaps = _facts(_blog(RECENT, PRIOR5))
    assert "블로그 감성 변화" not in gaps
    assert abs(f.items[f.key_of(LABEL)]["value"] - 0.3) < 1e-9
    assert f.key_of("블로그 감성(직전 7일, 기준선)")


def test_documents_older_than_14_days_are_not_in_the_comparison():
    old = [{"d": "2026-10-05", "source": "naver_blog", "n": 50, "score": -0.9}, {"d": "2026-10-10", "source": "naver_blog", "n": 50, "score": -0.9}]
    f, _ = _facts(_blog(RECENT, PRIOR5, extra=old))
    assert abs(f.items[f.key_of(LABEL)]["value"] - 0.3) < 1e-9          # 15일 이전 문서는 직전 창에 섞이지 않음


def test_gap_when_prior_window_has_fewer_than_5_days_or_20_docs():
    _, gaps = _facts(_blog(RECENT, PRIOR5[:4]))                          # 4일 24건 → 일수 부족
    assert gaps["블로그 감성 변화"] == "직전 7일 문서 24건·4일뿐 (최소 20건·5일)"
    _, gaps = _facts(_blog(RECENT, PRIOR5, n_prior=3))                  # 5일 15건 → 건수 부족
    assert "블로그 감성 변화" in gaps and "15건" in gaps["블로그 감성 변화"]
    _, gaps = _facts(_blog(RECENT, []))
    assert gaps["블로그 감성 변화"] == "직전 7일 자료 없음"


def test_rule_version_bumped_and_unchanged_agents_keep_measured_hit_rate(tmp_path):
    import json

    from ch_agents import outlook

    assert outlook.RULE_VERSION == "outlook-r1.1"
    p = tmp_path / "hit.json"
    ent = {"rate": 0.5, "n": 300, "period": "p", "basis": "b", "ci95": [0.45, 0.55],
           "nonOverlapping": {"neutralShare": 0.5, "baselines": {"random": {"rate": 0.5}}}}
    p.write_text(json.dumps({"ruleVersion": "outlook-r1", "agents": {"4": ent, "3": ent, "6": ent}}), encoding="utf-8")
    assert outlook.hit_rate(4, p)["status"] == "measured" and outlook.hit_rate(3, p)["status"] == "measured"
    assert outlook.hit_rate(6, p)["status"] == "unverified" and "규칙 버전" in outlook.hit_rate(6, p)["reason"]   # 감성 규칙은 창이 바뀜
