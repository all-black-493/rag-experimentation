"""Mirror the prompts in prompts/*.yaml into Langfuse prompt management.

    uv run python -m app.prompt_sync --dry-run
    uv run python -m app.prompt_sync

Git is the source of truth; Langfuse is a mirror. That direction is deliberate.
If prompts were authored in the Langfuse UI instead, editing one would change
production behaviour with no pull request, no eval run, and no regression gate -
the exact path the gate exists to close. Keeping them in the repo means a prompt
change is a code change and has to clear CI like any other.

What Langfuse gives us in return is the version history, the Playground, and -
because generations are linked to the prompt version that produced them - the
ability to ask "quality dropped on Tuesday; which prompt was live?" and group
metrics by the answer.

Run this after merging a prompt change and before (or during) deploy, so the
version the app links to is the version it renders from.
"""

import argparse
import sys

import yaml

from app.config import get_settings
from app.prompts import PROMPTS_DIR
from app.tracing import configure_tracing, get_client

# Only the chat prompts. responses.yaml holds the canned decline message, which
# is never sent to a model and so has nothing to manage here.
CHAT_PROMPTS = ("planner", "generation", "grounding", "profile", "review", "memo")

LABEL = "production"


def _messages(data: dict) -> list[dict]:
    return [
        {"role": "system", "content": data["system"]},
        {"role": "user", "content": data["human"]},
    ]


def _comparable(messages: list[dict]) -> list[tuple[str, str]]:
    """Role/content pairs only.

    Langfuse returns each message with an extra `type: "message"` key that we
    never send, so comparing the dicts directly always reports a difference and
    every run would push a redundant version.
    """
    return [(m["role"], m["content"]) for m in messages]


def _unchanged(existing, messages: list[dict], version: int) -> bool:
    """True when Langfuse already holds exactly this content at this version.

    Without the check, every deploy would push a new Langfuse version whose
    content is identical to the last, and the version history would stop meaning
    anything.
    """
    if existing is None:
        return False
    config = getattr(existing, "config", None) or {}
    return (
        _comparable(existing.prompt) == _comparable(messages)
        and config.get("yaml_version") == version
    )


def sync(dry_run: bool = False) -> int:
    client = get_client()
    if client is None:
        print("Langfuse not configured - nothing to sync.", file=sys.stderr)
        return 1

    changed = 0
    for name in CHAT_PROMPTS:
        data = yaml.safe_load((PROMPTS_DIR / f"{name}.yaml").read_text())
        messages = _messages(data)
        version = data["version"]

        try:
            existing = client.get_prompt(name, label=LABEL, cache_ttl_seconds=0)
        except Exception:  # noqa: BLE001 - a missing prompt is the first-run case
            existing = None

        if _unchanged(existing, messages, version):
            print(f"{name}: unchanged (yaml v{version})")
            continue

        changed += 1
        if dry_run:
            print(f"{name}: would push yaml v{version}")
            continue

        client.create_prompt(
            name=name,
            type="chat",
            prompt=messages,
            labels=[LABEL],
            config={"yaml_version": version},
            commit_message=f"sync from prompts/{name}.yaml v{version}",
        )
        print(f"{name}: pushed yaml v{version}")

    print(f"\n{changed} prompt(s) {'would change' if dry_run else 'changed'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report without pushing")
    args = parser.parse_args(argv)

    configure_tracing(get_settings())
    return sync(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
