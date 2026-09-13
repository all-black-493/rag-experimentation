from typing import Literal

# Set once by app.ingestion at load time, carried immutably through chunking,
# storage, and retrieval. Never inferred from - or influenced by - LLM output;
# citations are built from this, not from anything the model says about itself.
SourceType = Literal["pdf", "web", "text"]
