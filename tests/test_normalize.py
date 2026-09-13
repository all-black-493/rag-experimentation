from app.ingestion.normalize import normalize


def test_joins_hyphenated_line_breaks():
    """PDF line wrapping otherwise leaves 'inter-\\nnational' as two tokens."""
    assert normalize("an inter-\nnational treaty") == "an international treaty"


def test_replaces_non_breaking_space_with_a_real_space():
    """NBSP reads as a space but won't keyword-match one."""
    assert normalize("hotel\u00a0rate") == "hotel rate"


def test_strips_invisible_characters():
    assert normalize("7\u200b-ALPHA\ufeff-99") == "7-ALPHA-99"


def test_folds_ligatures_and_full_width_forms():
    assert normalize("ﬁle") == "file"
    assert normalize("Ｆｏｏ") == "Foo"


def test_collapses_runs_of_spaces_and_blank_lines():
    assert normalize("a     b\n\n\n\nc") == "a b\n\nc"


def test_preserves_paragraph_structure():
    """Single newlines carry meaning for chunking; only runs are collapsed."""
    assert normalize("line one\nline two\n\npara two") == "line one\nline two\n\npara two"


def test_normalizes_windows_line_endings():
    assert normalize("a\r\nb") == "a\nb"


def test_leaves_ordinary_text_untouched():
    text = "The maximum nightly hotel rate is $150 [1]."
    assert normalize(text) == text
