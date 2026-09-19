"""The citation graph: which documents cite which, extracted from the text.

Legal relationships are written in a recognisable form - a neutral citation,
a case number, "section 8 of the Sexual Offences Act" - so they are extracted
with patterns, not a model. Every edge keeps its provenance: the document and
chunk the citation sits in, and the citation as written. Nothing here is a
guess, and nothing here replaces the passages themselves as the source of
truth; the graph only widens what retrieval considers.
"""
