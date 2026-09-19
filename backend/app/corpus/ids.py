import hashlib

# Truncated to keep ids path- and URL-friendly, but deliberately not to 32: at
# that length a hex digest parses as a UUID, Weaviate's autoschema types it as
# its native `uuid`, and the value comes back in dashed form - so the id a
# citation carries would no longer be the id it was stored under. 40 hex
# characters cannot be read as a UUID, so what goes in is what comes out.
_ID_LENGTH = 40


def content_id(content: bytes | str) -> str:
    """Stable id for a document. Same input, same id, on every machine."""
    if isinstance(content, str):
        content = content.encode()
    return hashlib.sha256(content).hexdigest()[:_ID_LENGTH]
