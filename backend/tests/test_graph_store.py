from app.graph.edges import edges_for_chunk
from app.graph.refs import extract_references
from app.graph.resolve import IndexedDocument, Resolver
from app.graph.store import Graph, group_by_document

OUNDO = IndexedDocument(
    "d-oundo",
    "case_law",
    "Republic v Oundo (Criminal Case E028 of 2025) [2025] KEMC 174 (KLR) (8 August 2025) (Ruling)",
    "https://x/oundo",
)
LILYA = IndexedDocument(
    "d-lilya",
    "case_law",
    "Republic v Lilya (Sexual Offence E105 of 2021) [2025] KEMC 179 (KLR) (5 June 2025) (Judgment)",
    "https://x/lilya",
)
SOA = IndexedDocument("d-soa", "legislation", "Sexual Offences Act", "https://x/soa")
CONSTITUTION = IndexedDocument(
    "d-const", "legislation", "Constitution of Kenya →", "https://x/act/2010/constitution"
)


def test_resolves_by_neutral_citation_case_number_parties_and_act_title():
    resolver = Resolver([OUNDO, LILYA, SOA, CONSTITUTION])
    refs = {
        r.key: r
        for r in extract_references(
            "See [2025] KEMC 174 (KLR); Sexual Offence E105 of 2021; Republic v Lilya [2024] eKLR; "
            "section 8 of the Sexual Offences Act; Article 50 of the Constitution; "
            "Kaingu Elias Kasono v Republic Criminal Appeal No. 54 of 2010."
        )
    }
    assert resolver.resolve(refs["[2025] KEMC 174"]) == "d-oundo"
    assert resolver.resolve(refs["Sexual Offence E105 of 2021"]) == "d-lilya"
    assert resolver.resolve(refs["republic v lilya [2024]"]) == "d-lilya"
    assert resolver.resolve(refs["Sexual Offences Act"]) == "d-soa"
    assert resolver.resolve(refs["Constitution of Kenya"]) == "d-const"
    # Not in the corpus: recorded, unresolved.
    assert resolver.resolve(refs["Criminal Appeal 54 of 2010"]) is None


def test_a_document_citing_itself_makes_no_edge():
    resolver = Resolver([OUNDO])
    refs = extract_references("Republic v Oundo [2025] KEMC 174 (KLR)")
    assert edges_for_chunk(OUNDO, 0, refs, resolver) == []


def test_graph_indexes_citing_passages_by_key_parties_and_provision():
    resolver = Resolver([OUNDO, LILYA, SOA])
    refs = extract_references(
        "Kaingu Elias Kasono v Republic Criminal Appeal No. 54 of 2010; section 8(1) of the Sexual Offences Act"
    )
    graph = Graph()
    for e in edges_for_chunk(LILYA, 24, refs, resolver):
        graph.add(e.properties())

    kasono = graph.citing_passages("kaingu elias kasono v republic")
    assert [(n.via_doc_id, n.via_chunk_index) for n in kasono] == [("d-lilya", 24)]
    assert graph.citing_passages("Criminal Appeal 54 of 2010")[0].via_doc_id == "d-lilya"
    assert graph.citing_passages("Sexual Offences Act", "8(1)")[0].kind == "applies"
    assert graph.citing_passages("Sexual Offences Act")[0].provision == "8(1)"
    # Resolved statute: the Act knows who applied it; the unresolved case does not exist as a node.
    assert [n.doc_id for n in graph.cited_by["d-soa"]] == ["d-lilya"]
    assert graph.neighbours("d-lilya")[0].doc_id == "d-soa"
    assert graph.neighbours("d-soa")[0].doc_id == "d-lilya"
    # Either end can be opened: the neighbour carries the document's own URL.
    assert graph.neighbours("d-lilya")[0].url == "https://x/soa"
    assert graph.cited_by["d-soa"][0].url == LILYA.url
    assert graph.citing_passages("Criminal Appeal 54 of 2010")[0].url == LILYA.url


def test_links_group_every_citation_of_one_document():
    resolver = Resolver([OUNDO, LILYA, SOA])
    graph = Graph()
    for index, text in [
        (3, "section 8(1) of the Sexual Offences Act"),
        (9, "Kaingu Elias Kasono v Republic Criminal Appeal No. 54 of 2010"),
        (12, "section 11 of the Sexual Offences Act and section 8(1) of the Sexual Offences Act"),
    ]:
        for e in edges_for_chunk(LILYA, index, extract_references(text), resolver):
            graph.add(e.properties())

    links = group_by_document(graph.cites["d-lilya"])
    assert [(link.title or link.refs[0], link.refs) for link in links] == [
        ("Sexual Offences Act", ["section 8(1) of the Sexual Offences Act", "section 11 of the Sexual Offences Act"]),
        ("Criminal Appeal No. 54 of 2010", ["Criminal Appeal No. 54 of 2010"]),
    ]
    assert links[0].via_chunk_index == 3
    assert links[0].url == "https://x/soa"


def test_citing_passages_cover_documents_before_repeating_one():
    resolver = Resolver([OUNDO, LILYA, SOA])
    graph = Graph()
    for doc, index in [(LILYA, 9), (LILYA, 3), (OUNDO, 5)]:
        refs = extract_references("section 8 of the Sexual Offences Act")
        for e in edges_for_chunk(doc, index, refs, resolver):
            graph.add(e.properties())

    passages = graph.citing_passages("Sexual Offences Act", "8")
    assert [(n.via_doc_id, n.via_chunk_index) for n in passages] == [
        ("d-lilya", 3),
        ("d-oundo", 5),
        ("d-lilya", 9),
    ]
