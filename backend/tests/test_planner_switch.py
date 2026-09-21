from app.retrieval.filters import LegalFilters
from app.retrieval.planner import plan


class NeverCalledLLM:
    def with_structured_output(self, _schema):
        raise AssertionError("planner must not call the model when disabled")


def test_disabled_planner_yields_the_fallback_without_a_model_call():
    state = {"question": "q", "mode": "ask", "user_filters": LegalFilters()}

    result = plan(state, NeverCalledLLM(), catalog=lambda: None, max_subqueries=4, enabled=False)

    assert result["plan"].origin == "fallback"
    assert [s.collection for s in result["plan"].sub_queries] == ["legislation", "case_law"]
