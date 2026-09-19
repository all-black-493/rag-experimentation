"""Find citations in a passage of Kenyan legal text."""

import re
from dataclasses import dataclass
from typing import Literal

Kind = Literal["case", "statute"]


@dataclass(frozen=True)
class Reference:
    """One citation as written, with the pieces that identify what it points to."""

    kind: Kind
    # The citation text exactly as it appears.
    text: str
    # Case: a neutral citation like "[2025] KEMC 94 (KLR)" normalised to
    # "[2025] KEMC 94", or a case number like "Criminal Appeal E019 of 2025".
    # Statute: the Act's title, e.g. "Sexual Offences Act" or "Constitution".
    key: str
    # Statute only: the section or article cited.
    provision: str | None = None
    # Case only: the parties as written before the citation, when present -
    # "Kaingu Elias Kasono v Republic". How a lawyer names a case.
    parties: str | None = None


# "[2025] KEMC 94 (KLR)", "[2014] eKLR", "[1988] KLR 380". Kenya Law's own
# report series and the older law reports both appear.
_NEUTRAL = re.compile(
    r"\[(?P<year>(?:19|20)\d\d)\]\s*(?P<series>KE[A-Z]{2,5}|eKLR|KLR)(?:\s+(?P<number>\d+))?(?:\s*\(KLR\))?"
)

# "Criminal Appeal No. 54 of 2010", "Civil Suit E044 of 2024", "Cause No. 271
# of 2019", "Sexual Offence E105 of 2021" - the last with no type word after it.
_CASE_NUMBER = re.compile(
    r"(?P<kind>(?:(?:Civil|Criminal|Constitutional|Judicial Review|Miscellaneous|Succession|"
    r"Environment and Land|Employment and Labour Relations|Traffic|Commercial)\s)?"
    r"(?:Appeal|Application|Case|Cause|Petition|Suit|Reference|Revision)|Sexual Offence)\s+"
    r"(?:No\.?\s*)?(?P<number>E?\d+[A-Z]?)\s+of\s+(?P<year>(?:19|20)\d\d)",
    re.IGNORECASE,
)

# "section 26(1) of the Civil Procedure Act", "Section 215 of the Criminal
# Procedure Code", "rule 63 of the Probate and Administration Rules".
_STATUTE = re.compile(
    r"(?P<unit>[Ss]ection|[Ss]s?\.|[Rr]ule|[Rr]egulation|[Oo]rder|[Pp]aragraph)\s+"
    r"(?P<provision>\d+[A-Z]?(?:\s*\(\d+\))?(?:\s*\([a-z]\))?)\s+of\s+the\s+"
    r"(?P<title>[A-Z][A-Za-z’'&,\-]*(?:\s+(?:of|and|the|for|on|[A-Z][A-Za-z’'&,\-]*))*?\s"
    r"(?:Act|Code|Rules|Regulations|Order))"
)

_ARTICLE = re.compile(
    r"[Aa]rticle\s+(?P<provision>\d+[A-Z]?(?:\s*\(\d+\))?(?:\s*\([a-z]\))?)\s+of\s+the\s+Constitution"
)

# "Kaingu Elias Kasono v Republic" immediately before a citation. Capitalised
# words on each side of " v ", allowing "& another" / "& 2 others" and initials.
_PARTIES = re.compile(
    r"(?P<parties>[A-Z][\w'’&.\-]*(?:\s+(?:[A-Z][\w'’&.\-]*|&\s+\d+\s+others?|&\s+another|of|the))*"
    r"\s+v\.?\s+[A-Z][\w'’&.\-]*(?:\s+(?:[A-Z][\w'’&.\-]*|&\s+\d+\s+others?|&\s+another|of|the))*)"
    r"[\s,]*$"
)

# Legislation titles as cited often carry a year or a chapter the corpus's
# titles don't: "Employment Act, 2007", "Penal Code (Cap 63)".
_TITLE_NOISE = re.compile(r"(,?\s*(?:19|20)\d\d|\s*\(Cap\.?\s*\d+[A-Z]?\))\s*$")


def normalise_title(title: str) -> str:
    """The form a statute's title takes in both a citation and the corpus."""
    title = title.replace("\xa0", " ").strip()
    title = _TITLE_NOISE.sub("", title)
    title = re.sub(r"^(?:The|the)\s+", "", title)
    return re.sub(r"\s+", " ", title).strip()


_LEADING_NOISE = re.compile(
    r"^(?:See|In|Also|Cf\.?|And|But|Similarly|Further|Per|Held)\s+", re.IGNORECASE
)


def parties_key(parties: str) -> str:
    """Party names as a lookup key: case-folded, punctuation and noise words dropped."""
    parties = parties.replace("’", "'").lower()
    parties = re.sub(r"&\s+\d+\s+others?|&\s+another", " ", parties)
    parties = re.sub(r"\b(?:the|of)\b", " ", parties)
    parties = re.sub(r"[^a-z0-9 ]+", " ", parties)
    return re.sub(r"\s+", " ", parties).strip()


def _parties_before(text: str, end: int) -> str | None:
    """The party names written just before position `end`, if any."""
    window = text[max(0, end - 120) : end].replace("\xa0", " ")
    # Stop at sentence boundaries and at parentheses that open a case number.
    window = re.split(r"[.;:()\[\]]\s*", window)[-1]
    match = _PARTIES.search(window)
    if not match:
        return None
    return _LEADING_NOISE.sub("", match["parties"].strip()) or None


def neutral_key(year: str, series: str, number: str | None) -> str:
    return f"[{year}] {series.upper() if series != 'eKLR' else 'eKLR'}" + (
        f" {number}" if number else ""
    )


def case_number_key(kind: str, number: str, year: str) -> str:
    kind = re.sub(r"\s+", " ", kind.strip()).title()
    return f"{kind} {number.upper()} of {year}"


def extract_references(text: str) -> list[Reference]:
    """Every citation in the text, in order of appearance, de-duplicated."""
    text = text.replace("\xa0", " ")
    found: list[Reference] = []

    for m in _NEUTRAL.finditer(text):
        parties = _parties_before(text, m.start())
        if m["number"]:
            key = neutral_key(m["year"], m["series"], m["number"])
        elif parties:
            # "Moses Nato Raphael v Republic [2015] eKLR": no report number, but
            # the parties and year identify it the way a lawyer would.
            key = f"{parties_key(parties)} [{m['year']}]"
        else:
            # A bare "[2015] eKLR" names a year, not a case.
            continue
        found.append(Reference("case", m.group(0).strip(), key, parties=parties))
    for m in _CASE_NUMBER.finditer(text):
        kind = m["kind"] or ""
        # A bare "Case 3 of 2020" without a type is too ambiguous to resolve.
        if not kind.strip():
            continue
        found.append(
            Reference(
                "case",
                m.group(0).strip(),
                case_number_key(kind, m["number"], m["year"]),
                parties=_parties_before(text, m.start()),
            )
        )
    for m in _STATUTE.finditer(text):
        found.append(
            Reference(
                "statute",
                m.group(0).strip(),
                normalise_title(m["title"]),
                provision=re.sub(r"\s+", "", m["provision"]),
            )
        )
    for m in _ARTICLE.finditer(text):
        provision = re.sub(r"\s+", "", m["provision"])
        found.append(
            Reference(
                "statute",
                m.group(0).strip(),
                "Constitution of Kenya",
                provision=f"Article {provision}",
            )
        )

    seen: set[tuple] = set()
    unique = []
    for ref in found:
        signature = (ref.kind, ref.key, ref.provision)
        if signature not in seen:
            seen.add(signature)
            unique.append(ref)
    return unique
