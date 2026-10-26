from agent.tools import core_finance_peer_analyst, dart_sec_risk_examiner, macro_sentiment_tracker


def test_tool_sql_is_read_only():
    for mod in (core_finance_peer_analyst, dart_sec_risk_examiner, macro_sentiment_tracker):
        for name in dir(mod):
            if name.endswith("_SQL"):
                sql = getattr(mod, name).lower()
                assert sql.lstrip().startswith(("select", "with"))
                for word in ("insert ", "update ", "delete ", "drop ", "alter "):
                    assert word not in sql
