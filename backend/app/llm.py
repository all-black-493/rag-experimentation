"""The chat models, by role, from one provider or the other.

Two roles. `generation` writes answers, memos, reports and judges them;
`fast` plans, reviews, profiles and extracts - routing and reading, not
prose. Anthropic pairs Sonnet with Haiku; Ollama pairs whatever the machine
can run, which on a CPU is the same small model twice.

Nothing downstream knows which provider it has: every node takes a
`BaseChatModel`, calls `invoke` or `with_structured_output`, and reads
`.text`. Structured output on Ollama uses its JSON-schema API, so the same
Pydantic schemas work unchanged.
"""

from typing import Literal

from langchain_core.language_models import BaseChatModel

from app.config import Settings

Role = Literal["generation", "fast"]


def build_chat_model(settings: Settings, role: Role) -> BaseChatModel:
    if settings.llm_provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.ollama_model if role == "generation" else settings.ollama_fast_model,
            base_url=settings.ollama_base_url,
            # Ollama's default window is a few thousand tokens; a generation
            # prompt carries five parent windows, a memo's twelve.
            num_ctx=settings.ollama_num_ctx,
            num_predict=(
                settings.ollama_num_predict
                if role == "generation"
                else settings.ollama_num_predict_fast
            ),
            # Thinking models think by default and put it in the text. Off
            # unless asked: on a CPU it doubles every call, and the planner and
            # reviewer produce JSON, not reasoning.
            reasoning=settings.ollama_reasoning,
            temperature=settings.ollama_temperature,
            keep_alive=settings.ollama_keep_alive,
        )

    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(
        model=settings.generation_model if role == "generation" else settings.planner_model,
        anthropic_api_key=settings.anthropic_api_key,
        timeout=settings.external_timeout_seconds,
        max_retries=settings.external_max_retries,
    )
