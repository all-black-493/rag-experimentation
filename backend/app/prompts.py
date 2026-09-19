import logging
from dataclasses import dataclass
from pathlib import Path

import yaml
from langchain_core.prompts import ChatPromptTemplate

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

logger = logging.getLogger(__name__)


def _read_yaml(name: str) -> dict:
    path = PROMPTS_DIR / f"{name}.yaml"
    return yaml.safe_load(path.read_text())


@dataclass(frozen=True)
class VersionedPrompt:
    name: str
    version: int
    template: ChatPromptTemplate


def load_chat_prompt(name: str) -> VersionedPrompt:
    data = _read_yaml(name)
    template = ChatPromptTemplate.from_messages(
        [("system", data["system"]), ("human", data["human"])]
    )
    logger.info("loaded prompt %s v%d", name, data["version"])
    return VersionedPrompt(name=name, version=data["version"], template=template)


@dataclass(frozen=True)
class VersionedText:
    name: str
    version: int
    text: str


def load_text(name: str, field: str) -> VersionedText:
    data = _read_yaml(name)
    return VersionedText(name=name, version=data["version"], text=data[field].strip())
