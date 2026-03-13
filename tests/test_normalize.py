"""Tests for schemas/normalize.py — canonical normalize_key()."""

from normalize import normalize_key  # via conftest.py SCHEMAS_DIR path setup


class TestNormalizeKey:
    """Test the canonical normalize_key function."""

    def test_parenthetical_removal(self):
        """Parenthetical content is stripped."""
        assert normalize_key('Wholeness (W)') == 'wholeness'
        assert normalize_key('TAP (Transactional Analysis of Personality)') == 'tap'

    def test_special_chars_removed(self):
        """Hyphens, slashes, and other special characters are removed."""
        assert normalize_key('Cross-metathesis') == 'crossmetathesis'
        assert normalize_key('input/output') == 'inputoutput'
        assert normalize_key("Levinas's ethics") == 'levinass_ethics'

    def test_spaces_to_underscores(self):
        """Spaces become underscores."""
        assert normalize_key('Degrees of life') == 'degrees_of_life'
        assert normalize_key('  multiple   spaces  ') == 'multiple_spaces'

    def test_truncation_at_40(self):
        """Keys are truncated to 40 characters."""
        long_input = 'A' * 50
        result = normalize_key(long_input)
        assert len(result) == 40
        assert result == 'a' * 40

    def test_empty_string(self):
        """Empty input returns empty string."""
        assert normalize_key('') == ''
        assert normalize_key('   ') == ''

    def test_unicode_letters(self):
        """Unicode letters outside a-z are stripped."""
        assert normalize_key('über-mensch') == 'bermensch'
        assert normalize_key('résumé') == 'rsum'

    def test_numbers_preserved(self):
        """Digits are preserved."""
        assert normalize_key('TAP 2.0 model') == 'tap_20_model'

    def test_underscores_preserved(self):
        """Existing underscores pass through."""
        assert normalize_key('already_normalized') == 'already_normalized'
