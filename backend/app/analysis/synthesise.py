"""Across the documents: the issues, the conflicts, what to research - and the report."""

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from app.analysis.models import (
    Authority,
    CaseAnalysis,
    Contradiction,
    Issue,
    ResearchQuestion,
)
from app.prompts import load_chat_prompt
from app.tracing import linked_prompt, observation

ANALYSIS_PROMPT = load_chat_prompt("analysis")
REPORT_PROMPT = load_chat_prompt("report")


class Synthesis(BaseModel):
    issues: list[Issue] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    research_questions: list[ResearchQuestion] = Field(default_factory=list)


def _marked(text: str, sources: list[int] | int | None) -> str:
    if isinstance(sources, int):
        sources = [sources]
    return f"{text} " + " ".join(f"[{s}]" for s in sources or [])


def _material(analysis: CaseAnalysis) -> dict[str, str]:
    return {
        "parties": "\n".join(f"- {p.name} — {p.role}" for p in analysis.parties) or "none found",
        "facts": "\n".join(f"- {_marked(f.statement, f.source)}" for f in analysis.facts)
        or "none found",
        "chronology": "\n".join(
            f"- {e.when}: {_marked(e.description, e.source)}" for e in analysis.chronology
        )
        or "none found",
        "authorities": "\n".join(_authority_line(a) for a in analysis.authorities) or "none found",
    }


def _authority_line(a: Authority) -> str:
    held = (
        f"in the corpus as {a.title!r}, applied by {a.applied_by} judgments"
        if a.doc_id
        else "not in the corpus"
    )
    return f"- {a.ref} ({held}) " + " ".join(f"[{s}]" for s in a.sources)


def _invoke(llm: BaseChatModel, prompt, variables: dict, schema=None):
    message = prompt.template.invoke(variables)
    config = {"metadata": {"prompt": prompt.name, "prompt_version": prompt.version}}
    with linked_prompt(prompt.name):
        if schema is not None:
            return llm.with_structured_output(schema).invoke(message, config=config)
        return llm.invoke(message, config=config).text


def synthesise(llm: BaseChatModel, analysis: CaseAnalysis) -> Synthesis:
    with observation(
        as_type="chain",
        name="synthesise-analysis",
        input={"facts": len(analysis.facts), "documents": len(analysis.sources)},
        metadata={"prompt": ANALYSIS_PROMPT.name, "prompt_version": ANALYSIS_PROMPT.version},
    ) as span:
        result = _invoke(llm, ANALYSIS_PROMPT, _material(analysis), Synthesis)
        span.update(
            output={
                "issues": len(result.issues),
                "contradictions": len(result.contradictions),
                "questions": len(result.research_questions),
            }
        )
        return result


def write_report(llm: BaseChatModel, analysis: CaseAnalysis) -> str:
    with observation(
        as_type="chain",
        name="write-report",
        input={"facts": len(analysis.facts)},
        metadata={"prompt": REPORT_PROMPT.name, "prompt_version": REPORT_PROMPT.version},
    ) as span:
        variables = {
            **_material(analysis),
            "issues": "\n".join(f"- {_marked(i.question, i.sources)}" for i in analysis.issues)
            or "none found",
            "contradictions": "\n".join(
                f"- {c.point}: {c.first!r} against {c.second!r} "
                + " ".join(f"[{s}]" for s in c.sources)
                for c in analysis.contradictions
            )
            or "none found",
            "questions": "\n".join(f"- {q.question} ({q.why})" for q in analysis.research_questions)
            or "none",
        }
        report = _invoke(llm, REPORT_PROMPT, variables)
        span.update(output={"chars": len(report)})
        return report
