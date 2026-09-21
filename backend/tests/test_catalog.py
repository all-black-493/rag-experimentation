from app.retrieval.catalog import Catalog, CollectionInfo, CourtInfo


def test_planner_description_lists_collections_courts_and_years():
    catalog = Catalog(
        collections=[
            CollectionInfo(
                key="legislation",
                label="Legislation",
                description="Acts.",
                documents=543,
                passages=40000,
                year_min=1902,
                year_max=2026,
            ),
            CollectionInfo(
                key="case_law",
                label="Case law",
                description="Judgments.",
                documents=990,
                passages=20000,
                year_min=2024,
                year_max=2026,
                courts=[
                    CourtInfo(code="kemc", name="Magistrates' Courts", rank=4, documents=457),
                    CourtInfo(code="kesc", name="Supreme Court", rank=1, documents=7),
                ],
            ),
        ]
    )

    text = catalog.for_planner()

    assert "- legislation: Acts. 543 documents, 1902–2026." in text
    assert "- case_law: Judgments. 990 documents, 2024–2026." in text
    # Highest court first, so the planner reads the hierarchy top-down.
    assert text.index("kesc = Supreme Court (7)") < text.index("kemc = Magistrates' Courts (457)")
    assert catalog.court_codes() == {"kemc", "kesc"}


def test_missing_year_bounds_are_stated_rather_than_invented():
    catalog = Catalog(
        collections=[
            CollectionInfo(key="legislation", label="L", description="D.", documents=1, passages=1)
        ]
    )
    assert "years unknown" in catalog.for_planner()
