from app.prompts import load_chat_prompt, load_text


def test_load_chat_prompt_reads_version_and_renders_template():
    prompt = load_chat_prompt("generation")

    assert prompt.name == "generation"
    assert prompt.version >= 1

    rendered = prompt.template.invoke({"context": "ctx", "question": "q"})
    contents = [message.content for message in rendered.to_messages()]
    assert any("ctx" in content for content in contents)
    assert any("q" in content for content in contents)


def test_load_text_reads_version_and_strips_whitespace():
    text = load_text("responses", "decline_message")

    assert text.name == "responses"
    assert text.version >= 1
    assert text.text == text.text.strip()
    assert text.text
