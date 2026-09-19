from datetime import date

from app.corpus.documents import join_windows, parse_date, reconstruct


def windows_of(text: str, size: int = 800, overlap: int = 150) -> list[str]:
    """Cut text the way the corpus was cut: fixed windows, fixed overlap."""
    step = size - overlap
    return [text[i : i + size] for i in range(0, max(1, len(text) - overlap), step)]


def test_fixed_overlap_windows_join_back_to_the_original():
    text = "".join(f"Section {i}. The provisions of this Act apply. " for i in range(120))

    joined, fallbacks = join_windows(windows_of(text))

    assert joined == text
    assert fallbacks == 0


def test_short_final_window_is_handled():
    text = "x" * 1000  # last window is 200 chars: 150 overlap + 50 new
    joined, _ = join_windows(windows_of(text))
    assert joined == text


def test_windows_that_do_not_overlap_are_joined_on_a_line_break_and_counted():
    joined, fallbacks = join_windows(["first window entirely", "unrelated second window"])

    assert joined == "first window entirely\nunrelated second window"
    assert fallbacks == 1


def test_a_window_that_is_pure_overlap_adds_nothing():
    joined, _ = join_windows(["abcdefghij", "hij"], overlap=3)
    assert joined == "abcdefghij"


def row(url, index, text, kind="case_law", title="T", date_value=None, chunk_id=None):
    return {
        "chunk_id": chunk_id or f"{url}##chunk{index}",
        "text": text,
        "metadata": {
            "title": title,
            "url": url,
            "type": kind,
            "chunk_index": index,
            "total_chunks": 2,
            "citation": "",
            "court": "",
            "date": date_value,
        },
    }


def test_reconstruct_parses_judgment_provenance_from_the_url():
    url = "https://new.kenyalaw.org/akn/ke/judgment/kesc/2025/12/eng@2025-06-01"
    docs = reconstruct([row(url, 0, "a" * 800, date_value="June 1, 2025")])

    doc = docs[0]
    assert doc.collection == "case_law"
    assert doc.court_code == "kesc"
    assert doc.court == "Supreme Court"
    assert doc.decision_date == date(2025, 6, 1)
    assert doc.year == 2025
    assert doc.version_date == date(2025, 6, 1)


def test_reconstruct_parses_act_provenance_including_gazette_notices():
    act = "https://new.kenyalaw.org/akn/ke/act/1989/17/eng@2025-12-11"
    notice = "https://new.kenyalaw.org/akn/ke/act/gn/2024/12/eng@2024-02-02"
    constitution = "https://new.kenyalaw.org/akn/ke/act/2010/constitution"

    docs = {
        d.url: d
        for d in reconstruct(
            [
                row(act, 0, "x", kind="legislation", title="Capital Markets Act"),
                row(notice, 0, "y", kind="legislation"),
                row(constitution, 0, "z", kind="legislation"),
            ]
        )
    }

    assert docs[act].year == 1989 and docs[act].version_date == date(2025, 12, 11)
    assert docs[notice].year == 2024
    assert docs[constitution].year == 2010 and docs[constitution].version_date is None
    assert all(d.court_code is None for d in docs.values())


def test_judgment_without_a_parsable_date_falls_back_to_the_url_year():
    url = "https://new.kenyalaw.org/akn/ke/judgment/kehc/2024/7/eng@2024-03-03"
    doc = reconstruct([row(url, 0, "a", date_value="")])[0]

    assert doc.decision_date is None
    assert doc.year == 2024


def test_duplicate_rows_collapse_and_order_follows_chunk_index():
    url = "https://new.kenyalaw.org/akn/ke/judgment/kemc/2025/1/eng@2025-01-01"
    first, second = "A" * 800, "A" * 150 + "B" * 650
    docs = reconstruct(
        [row(url, 1, second), row(url, 0, first), row(url, 0, first)]  # out of order + duplicate
    )

    assert len(docs) == 1
    assert docs[0].text == "A" * 800 + "B" * 650
    assert docs[0].fallback_joins == 0


def test_doc_id_is_stable_and_not_uuid_shaped():
    url = "https://new.kenyalaw.org/akn/ke/judgment/kemc/2025/1/eng@2025-01-01"
    a = reconstruct([row(url, 0, "t")])[0].doc_id
    b = reconstruct([row(url, 0, "t")])[0].doc_id

    assert a == b
    assert len(a) == 40


def test_parse_date_accepts_the_corpus_format_and_non_breaking_spaces():
    assert parse_date("May\xa015,\xa02025") == date(2025, 5, 15)
    assert parse_date("not a date") is None
    assert parse_date(None) is None


def test_breadcrumb_arrow_is_not_part_of_a_title():
    act = "https://new.kenyalaw.org/akn/ke/act/2010/constitution"
    docs = reconstruct([row(act, 0, "x", kind="legislation", title="Constitution of Kenya\xa0\u2192")])
    assert docs[0].title == "Constitution of Kenya"
