"""The matter as the planner reads it: what documents it holds and what each is."""

from app.matters.models import Matter


def describe_matter(matter: Matter) -> str:
    """A catalog entry in the same prose as the corpus collections'."""
    indexed = [d for d in matter.documents if d.status == "indexed"]
    heading = (
        f'- matter: The user\'s own documents for the matter "{matter.name}" '
        f"({len(indexed)} documents). Use for what the user's documents say - their "
        "contracts, pleadings, letters, statements, evidence - and for the facts of the "
        "matter. Not for what the law says."
    )
    lines = [heading]
    for document in indexed:
        profile = document.profile
        if profile is None:
            lines.append(f"  - {document.name}")
            continue
        parties = f" Parties: {', '.join(profile.parties)}." if profile.parties else ""
        lines.append(f"  - {document.name} — {profile.document_type}: {profile.summary}{parties}")
    return "\n".join(lines)
