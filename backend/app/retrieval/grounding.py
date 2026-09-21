from pydantic import BaseModel, Field

from app.prompts import load_chat_prompt, load_text

VERIFY_PROMPT = load_chat_prompt("grounding")
DECLINE_MESSAGE = load_text("responses", "decline_message").text


class GroundednessCheck(BaseModel):
    grounded: bool = Field(
        description="True only if every claim in the candidate answer is directly "
        "supported by the given context passages."
    )
    reason: str = Field(description="One sentence explaining the judgment.")
