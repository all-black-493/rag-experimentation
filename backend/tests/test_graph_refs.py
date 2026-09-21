from app.graph.refs import extract_references, normalise_title, parties_key


def keys(text):
    return [(r.kind, r.key, r.provision) for r in extract_references(text)]


def test_neutral_citations_and_case_numbers_are_found_with_their_parties():
    refs = extract_references(
        "In Kaingu Elias Kasono v Republic Criminal Appeal No. 54 of 2010 the court held so; "
        "see Republic v Oundo [2025] KEMC 174 (KLR)."
    )
    by_key = {r.key: r for r in refs}
    assert by_key["Criminal Appeal 54 of 2010"].parties == "Kaingu Elias Kasono v Republic"
    assert by_key["[2025] KEMC 174"].parties == "Republic v Oundo"


def test_statute_sections_and_constitution_articles_are_found():
    assert keys(
        "Under section 8(1) of the Sexual Offences Act and Article 50 (2) (a) of the Constitution"
    ) == [
        ("statute", "Sexual Offences Act", "8(1)"),
        ("statute", "Constitution of Kenya", "Article 50(2)(a)"),
    ]


def test_a_bare_year_only_eklr_citation_names_nothing():
    assert keys("as was held in [2014] eKLR generally") == []


def test_a_party_named_eklr_citation_is_kept():
    refs = extract_references("Moses Nato Raphael v Republic [2015] eKLR is authority for this.")
    assert refs[0].key == "moses nato raphael v republic [2015]"


def test_leading_words_are_not_parties():
    refs = extract_references("See Republic v Oundo [2025] KEMC 174 (KLR).")
    assert refs[0].parties == "Republic v Oundo"


def test_repeated_citations_in_one_passage_count_once():
    text = "section 8 of the Sexual Offences Act ... section 8 of the Sexual Offences Act"
    assert len(extract_references(text)) == 1


def test_title_and_party_normalisation():
    assert normalise_title("The Employment Act, 2007") == "Employment Act"
    assert normalise_title("Penal Code (Cap 63)") == "Penal Code"
    assert parties_key("Estate of Japheth Amaayi & another v Salina Transporters") == (
        "estate japheth amaayi v salina transporters"
    )
