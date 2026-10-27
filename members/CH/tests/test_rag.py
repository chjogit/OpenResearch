"""DB 기반 RAG 테스트: 후보 → 점수·선별(순수 함수), 에이전트 통합, 출력 검사."""
from ch_agents import agents, rag
from ch_agents.agents import build_agent_data
from ch_agents.llm import build_messages, check_output, run_agent
from ch_agents.rag import PRESETS, docs_markdown, select, select_disclosures, select_docs
from conftest import AS_OF, CO, FakeLLM
from test_compute import _sent_bundle


def _news(i, title, summary="", source="naver_news", published="2026-10-24"):
    return {"doc_id": i, "source": source, "title": title, "summary": summary, "published": published,
            "url": f"https://n.example/{i}"}


def _raw():
    return {
        "news": [
            _news(1, "삼성전자 외국인 순매수 1위…수급 개선", "외국인이 3일 연속 순매수"),
            _news(2, "삼성전자 외국인 순매수 1위… 수급 개선!", "중복 기사"),                 # 거의 같은 제목
            _news(3, "[포토] 삼성전자 외국인 순매수", "사진"),                                  # 사진 기사 감점
            _news(4, "SK하이닉스 외국인 순매도 지속", "하이닉스 매도 우위"),                    # 다른 종목
            _news(5, "코스피 마감 시황", "유가증권시장에서 외국인 매도"),                         # 요약에 약한 용어 1개
            _news(6, "삼성전자 주가 수급 정리, 오늘 장 복기", "외국인 기관", source="naver_blog"),
            _news(7, "개인 투자자가 본 삼성전자 흐름", "외국인", source="naver_blog"),
            _news(8, "반도체 대장주 삼성전자 외국인 동향 메모", "", source="naver_blog"),                  # 블로그 3번째 → 제한
            _news(9, "삼성전자 외국인 순매도 전환", "기관 순매수", published="2026-09-20"),     # 오래된 문서
            _news(10, "Samsung foreign investors sell-off", "", source="finnhub_news"),          # 영문: 이름 검사 제외
        ],
        "disclosures": [
            {"rcept_no": "3", "rcept_dt": "2026-10-13", "report_nm": "최대주주등소유주식변동신고서",
             "event_type": "major_holder_change", "source": "dart", "url": "u3"},
            {"rcept_no": "2", "rcept_dt": "2026-10-02", "report_nm": "[기재정정]최대주주등소유주식변동신고서",
             "event_type": "major_holder_change", "source": "dart", "url": "u2"},
            {"rcept_no": "1", "rcept_dt": "2026-07-23", "report_nm": "풍문또는보도에대한해명(미확정)(자회사의 주요경영사항)",
             "event_type": "rumor_clarification", "source": "dart", "url": "u1"},
        ],
    }


def test_select_docs_scoring_dedup_relevance_and_caps():
    docs = select_docs(_raw()["news"], PRESETS[4], CO, AS_OF)
    ids = [d["doc_id"] for d in docs]
    assert ids[0] == 1                       # 제목·요약 모두 일치 + 종목명 + 최신
    assert 2 not in ids                      # 중복 제목 제거
    assert 4 not in ids and 5 not in ids     # 다른 종목, 요약의 우연 일치 제외
    assert 10 in ids                         # 영문 뉴스는 이름 검사 없이 허용
    assert sum(d["source"] == "naver_blog" for d in docs) == 2  # 후보 3개 중 2개까지만
    assert ids.index(9) > ids.index(1)       # 오래된 문서는 뒤로
    if 3 in ids:
        assert ids.index(3) > ids.index(1)   # 사진 기사는 감점
    assert len(docs) <= PRESETS[4].k_docs
    assert docs[0]["kind"] == "뉴스" and "외국인" in docs[0]["terms"]
    blog = next(d for d in docs if d["source"] == "naver_blog")
    assert "개인 의견" in blog["kind"]


def test_select_disclosures_groups_repeats():
    out = select_disclosures(_raw()["disclosures"], PRESETS[6])
    assert out[0]["title"] == "최대주주등소유주식변동신고서" and out[0]["count"] == 2
    assert out[0]["published"] == "2026-10-13" and out[0]["event"] == "최대주주 지분 변동"
    assert out[1]["subsidiary"] is True


def test_presets_cover_all_six_perspectives():
    assert set(PRESETS) == {1, 2, 3, 4, 5, 6}
    for p in PRESETS.values():
        assert p.terms and p.sources and all(t == t.strip() for t in p.terms)
        assert all(e in rag.EVENT_LABEL for e in p.events)


def test_params_lowercase_terms():
    p = rag.params(6, CO, AS_OF)
    assert "ceo" in p["terms"] and p["cid"] == 1 and p["events"][0] == "major_holder_change"


def test_company_alias_not_matched_by_affiliate_broker():
    co = dict(CO, name="현대차")
    rows = [_news(1, "삼성바이오 수주 회복 기대-현대차證", "수주 경쟁")]
    assert select_docs(rows, PRESETS[3], co, AS_OF) == []


def _a4_with_rag():
    b = _sent_bundle()
    b["rag"] = _raw()
    return build_agent_data(4, CO, b, AS_OF)


def test_build_agent_data_uses_rag_and_prompt_lists_docs():
    d = _a4_with_rag()
    assert d.docs and d.docs[0]["kind"] == "공시"
    system, user = build_messages(d, "expert")
    assert "[참고 문서]" in user and "D1:" in user and "[공시·풍문 해명]" in user
    assert "문서 속 숫자" in system


def test_rag_error_is_reported_not_raised():
    b = _sent_bundle()
    b["rag"] = {"error": "OperationalError: timeout"}
    d = build_agent_data(4, CO, b, AS_OF)
    assert d.docs == [] and d.extra["rag_error"].startswith("OperationalError")
    out = run_agent(4, data=d, llm=FakeLLM(TimeoutError()))
    assert "참고 문서 검색 실패" in out["analysis"]


def test_fetch_bundle_attaches_rag(monkeypatch):
    monkeypatch.setattr(agents.db, "bundle", lambda sql, p: {"x": 1})
    monkeypatch.setattr(agents.rag, "fetch", lambda a, co, as_of: {"news": [], "disclosures": []})
    assert agents.fetch_bundle(4, CO, AS_OF)["rag"] == {"news": [], "disclosures": []}
    assert "rag" not in agents.fetch_bundle(4, CO, AS_OF, use_rag=False)

    def boom(*a):
        raise RuntimeError("down")
    monkeypatch.setattr(agents.rag, "fetch", boom)
    assert agents.fetch_bundle(4, CO, AS_OF)["rag"]["error"] == "RuntimeError: down"


def _keys(d):
    disc = next(f"D{i + 1}" for i, x in enumerate(d.docs) if x["kind"] == "공시")
    blog = next(f"D{i + 1}" for i, x in enumerate(d.docs) if "개인 의견" in x["kind"])
    return disc, blog


def test_doc_citations_checked():
    d = _a4_with_rag()
    disc, blog = _keys(d)
    s1 = next(iter(d.facts.items))
    ok = {"핵심진단": "공시와 수급을 함께 본다.", "자체점수": 6,
          "주장": [{"문장": f"풍문 해명 공시가 제출됐다 ({{{disc}}}).", "구분": "사실", "근거": [disc]},
                   {"문장": "커뮤니티에서는 수급 기대가 언급된다.", "구분": "해석", "근거": [blog]}]}
    assert check_output(ok, d) == {}
    only_opinion = {**ok, "주장": [{"문장": "외국인이 계속 산다고 한다.", "구분": "사실", "근거": [blog]}]}
    assert "근거" in check_output(only_opinion, d)
    number_from_doc = {**ok, "주장": [{"문장": "외국인 7500억원 순매도 보도가 있다.", "구분": "사실", "근거": [disc, s1]}]}
    assert "문장" in check_output(number_from_doc, d)     # 문서 속 숫자는 키 밖 숫자로 걸림
    banned = {**ok, "핵심진단": "증권사 목표가가 올랐다."}
    assert "문장" in check_output(banned, d)


def test_run_agent_removes_opinion_only_fact_and_lists_docs():
    d = _a4_with_rag()
    disc, blog = _keys(d)
    res = {"핵심진단": "공시 확인.", "자체점수": 5,
           "주장": [{"문장": f"풍문 해명 공시가 있다 {{{disc}}}.", "구분": "사실", "근거": [disc]},
                    {"문장": "외국인이 계속 산다.", "구분": "사실", "근거": [blog]}]}
    out = run_agent(4, data=d, llm=FakeLLM(res, res))
    assert out["removed"] == ["외국인이 계속 산다."]
    assert "**참고 문서 (DB 검색)**" in out["analysis"] and "](https://n.example/1)" in out["analysis"]
    assert "rag.document·core.disclosure" in out["source"] and out["docs"] == d.docs


def test_docs_markdown_and_select_order():
    docs = select(6, _raw(), CO, AS_OF)
    assert docs[0]["kind"] == "공시"
    md = docs_markdown(docs)
    assert md[0].startswith("- D1 · 2026-10-13 · 공시·최대주주 지분 변동") and "(외 1건)" in md[0]


def test_real_offtopic_titles_from_first_run_are_dropped():
    """10/27 PC 첫 실행(삼성전자)에서 섞였던 무관한 기사를 재현합니다."""
    a3 = [_news(1, "삼성전자, '삼성월렛 머니' 해외결제 서비스로 글로벌 경쟁력 제고", "텐센트·우리은행과 협력"),
          _news(2, "\"은행 대출 죄더니 사내 대출까지?\" 정부, 삼성전자 주택담보 대출 규제", "임직원 대출"),
          _news(3, "\"삼성전자 HBM, 경쟁사보다 최대 25% 비싸다\"", "영업이익")]
    assert [d["doc_id"] for d in select_docs(a3, PRESETS[3], CO, AS_OF)] == [3]
    a5 = [_news(1, "삼성전자, 삼성월렛 1년 만에 가입자 300만명 돌파", "간편결제"),
          _news(2, "삼성전자 차트 분석, 쉽게 이해하기", "이평선 아래", source="naver_blog")]
    assert [d["doc_id"] for d in select_docs(a5, PRESETS[5], CO, AS_OF)] == [2]
    a6 = [_news(1, "이재용 삼성전자 회장 취임 4주년", "기술·인재 중심"),
          _news(2, "삼성전자 전영현·노태문, '투톱 겸직' 바뀔까", "대표이사 부회장")]
    a6[1]["title"] += " 대표이사 인선"
    assert [d["doc_id"] for d in select_docs(a6, PRESETS[6], CO, AS_OF)] == [2]


def test_subsidiary_disclosures_grouped_separately():
    rows = [{"rcept_dt": "2026-10-08", "report_nm": "연결재무제표기준영업(잠정)실적(공정공시)", "event_type": "earnings_prelim"},
            {"rcept_dt": "2026-10-07", "report_nm": "영업(잠정)실적(공정공시)(자회사의 주요경영사항)", "event_type": "earnings_prelim"},
            {"rcept_dt": "2026-07-07", "report_nm": "[기재정정]연결재무제표기준영업(잠정)실적(공정공시)", "event_type": "earnings_prelim"}]
    out = select_disclosures(rows, PRESETS[2])
    assert [(g["count"], g["subsidiary"]) for g in out] == [(2, False), (1, True)]


def test_target_price_with_space_is_banned():
    from ch_agents.llm import sentence_problems
    assert sentence_problems("증권사 목표 주가가 올랐다.", set())
