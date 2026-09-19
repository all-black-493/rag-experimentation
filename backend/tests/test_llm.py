"""One factory, two providers, two roles; nothing downstream can tell which it got."""

from app.config import Settings
from app.llm import build_chat_model


def test_anthropic_pairs_the_generation_model_with_the_planner_model():
    settings = Settings(llm_provider="anthropic", anthropic_api_key="k")
    generation = build_chat_model(settings, "generation")
    fast = build_chat_model(settings, "fast")
    assert type(generation).__name__ == "ChatAnthropic"
    assert generation.model == settings.generation_model
    assert fast.model == settings.planner_model


def test_ollama_uses_the_local_models_with_a_window_that_fits_a_memo():
    settings = Settings(
        llm_provider="ollama",
        ollama_base_url="http://ollama:11434",
        ollama_model="qwen3:14b",
        ollama_fast_model="qwen3:8b",
    )
    generation = build_chat_model(settings, "generation")
    fast = build_chat_model(settings, "fast")
    assert type(generation).__name__ == "ChatOllama"
    assert (generation.model, fast.model) == ("qwen3:14b", "qwen3:8b")
    assert generation.base_url == "http://ollama:11434"
    assert generation.num_ctx == 16384
    # Thinking off: on a CPU it doubles every call, and structured output needs none of it.
    assert generation.reasoning is False
    # The verifier's uncached copy works on either provider.
    assert generation.model_copy(update={"cache": False}).model == "qwen3:14b"
