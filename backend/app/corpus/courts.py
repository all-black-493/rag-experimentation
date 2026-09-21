"""Kenyan court codes as they appear in Kenya Law URLs.

The corpus's own `court` field is empty on every row; the code in the URL path
(`/judgment/kesc/2025/12/`) is the reliable source. This is the one place the
mapping lives - the schema, the planner's catalog and the UI all read it from
here, so a new court is a one-line change.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Court:
    code: str
    name: str
    # Rough seniority, highest first. Lets a UI order courts sensibly rather than
    # alphabetically, and gives the planner a sense of which court binds which.
    rank: int


COURTS: dict[str, Court] = {
    c.code: c
    for c in (
        Court("kesc", "Supreme Court", 1),
        Court("keca", "Court of Appeal", 2),
        Court("kehc", "High Court", 3),
        Court("keelc", "Environment and Land Court", 3),
        Court("keelrc", "Employment and Labour Relations Court", 3),
        Court("kemc", "Magistrates' Courts", 4),
        Court("kekc", "Kadhis' Courts", 4),
    )
}


def court_name(code: str) -> str:
    """Display name for a court code, or the code itself if it's one we don't know.

    Falling through rather than failing: an unfamiliar code in a future corpus
    drop should still ingest, and show up as itself, not abort the whole run.
    """
    court = COURTS.get(code)
    return court.name if court else code.upper()
