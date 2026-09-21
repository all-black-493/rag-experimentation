# Corpus

`all_chunks.json` — Kenyan legislation and case law scraped from
[new.kenyalaw.org](https://new.kenyalaw.org), pre-chunked into 800-character
windows with a 150-character overlap. 63,603 rows, 1,533 documents (543 Acts,
990 judgments). Not committed (75 MB); place the file here.

Ingest with the stack running:

    docker compose exec app python -m app.corpus.ingest /corpus/all_chunks.json

Row shape: `{chunk_id, text, metadata: {title, url, type, chunk_index, total_chunks, date, ...}}`.
The pipeline reconstructs whole documents from the windows and re-chunks them;
see `backend/app/corpus/documents.py`.
