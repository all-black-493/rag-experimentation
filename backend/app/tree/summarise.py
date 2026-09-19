"""One model call per cluster: the paragraph a search can find the passages by."""

from langchain_core.language_models import BaseChatModel

from app.prompts import load_chat_prompt
from app.tracing import linked_prompt, observation

SUMMARY_PROMPT = load_chat_prompt("summary")

# What the model reads per passage: enough to summarise, bounded per cluster.
_PASSAGE_CHARS = 1_200


def summarise(llm: BaseChatModel, passages: list[str]) -> tuple[str, str]:
    """(summary, title) for one cluster."""
    with observation(
        as_type="chain",
        name="summarise-cluster",
        input={"passages": len(passages)},
        metadata={"prompt": SUMMARY_PROMPT.name, "prompt_version": SUMMARY_PROMPT.version},
    ) as span:
        rendered = "\n\n".join(f"- {p[:_PASSAGE_CHARS]}" for p in passages)
        message = SUMMARY_PROMPT.template.invoke({"passages": rendered})
        with linked_prompt(SUMMARY_PROMPT.name):
            text = llm.invoke(
                message,
                config={
                    "metadata": {
                        "prompt": SUMMARY_PROMPT.name,
                        "prompt_version": SUMMARY_PROMPT.version,
                    }
                },
            ).text
        summary, title = split_title(text)
        span.update(output={"title": title, "chars": len(summary)})
        return summary, title


def split_title(text: str) -> tuple[str, str]:
    """The last "Title:" line is the title; the rest is the summary."""
    lines = [line for line in text.strip().splitlines() if line.strip()]
    title = ""
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip().lower().startswith("title:"):
            title = lines[i].split(":", 1)[1].strip().strip("*\"' ")
            lines = lines[:i] + lines[i + 1 :]
            break
    summary = " ".join(line.strip() for line in lines).strip()
    return summary, title or summary[:60]
