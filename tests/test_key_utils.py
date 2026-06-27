"""
Unit tests for core.key_utils.

These tests don't need the databse, Redis, or FastAPI - they exercise
the key helpers in isolation. Foundation being tested without any of 
the surrounding infrastructure.
"""
import pytest

from core.key_utils import generate_api_key, parse_api_key, verify_api_key

class TestGenerateApiKey:
    def test_returns_three_values(self):
        full_key, prefix, key_hash = generate_api_key()
        assert isinstance(full_key, str)
        assert isinstance(prefix, str)
        assert isinstance(key_hash, str)

    def test_full_key_has_expected_format(self):
        full_key, prefix, key_hash = generate_api_key()
        assert full_key.startswith("qfk_")
        # qfk_ + 8 chars + _ + 32 chars = 45 total
        assert len(full_key) >= 44

    def test_prefix_is_8_chars(self):
        full_key, prefix, key_hash = generate_api_key()
        assert len(prefix) == 8

    def test_prefix_matches_what_appears_in_full_key(self):
        full_key, prefix, key_hash = generate_api_key()
        assert full_key.startswith(f"qfk_{prefix}_")
    
    def test_keys_are_unique(self):
        keys = {generate_api_key()[0] for _ in range(100)}
        assert len(keys) == 100 # 100 unique keys generated

    def test_prefixes_are_unique(self):
        # With 8 url-safe chars (~48 bits) and 100 samples, collision
        # probability is vanishingly small. Empirical sanity check only.
        prefixes = {generate_api_key()[1] for _ in range(100)}
        assert len(prefixes) == 100

    def test_hash_verifies_the_full_key(self):
        full_key, prefix, key_hash = generate_api_key()
        assert verify_api_key(full_key, key_hash) is True

class TestParseApiKey:
    def test_parses_well_formed_key(self):
        full_key, prefix, key_hash = generate_api_key()
        result = parse_api_key(full_key)
        assert result is not None
        parsed_prefix, parsed_secret = result
        assert parsed_prefix == prefix
        assert len(parsed_secret) > 0

    def test_returns_none_for_missing_prefix(self):
        assert parse_api_key("just-a-random-string") is None

    def test_returns_none_for_wrong_prefix(self):
        assert parse_api_key("xyz_abc12345_secret") is None
    
    def test_returns_none_for_missing_secret(self):
        assert parse_api_key("qfk_abc12345_") is None
    
    def test_returns_none_for_empty_string(self):
        assert parse_api_key("") is None

    def test_returns_none_for_non_string(self):
        assert parse_api_key(None) is None
        assert parse_api_key(123) is None
    
    def test_rejects_prefix_with_special_chars(self):
        # @ and ! aren't in URL-safe base64
        assert parse_api_key("qfk_abc!@345_secret") is None

class TestVerifyApiKey:
    def test_verifies_correct_key(self):
        full_key, prefix, key_hash = generate_api_key()
        assert verify_api_key(full_key, key_hash) is True

    def test_rejects_wrong_key(self):
        full_key, prefix, key_hash = generate_api_key()
        other_key, prefix2, key_hash2 = generate_api_key()
        assert verify_api_key(other_key, key_hash) is False

    def test_rejects_modified_key(self):
        full_key, prefix, key_hash = generate_api_key()
        tampered_key = full_key[:-1] + ("X" if full_key[-1] != "X" else "Y")
        assert verify_api_key(tampered_key, key_hash) is False

    def test_returns_false_for_malformed_hash(self):
        full_key, prefix, key_hash = generate_api_key()
        assert verify_api_key(full_key, "not-a-bcrypt-hash") is False

    def test_returns_false_for_non_string_inputs(self):
        assert verify_api_key(None, "hash") is False
        assert verify_api_key("key", None) is False
        assert verify_api_key(123, 456) is False

    def test_returns_false_for_empty_inputs(self):
        # Empty key won't match a real hash
        full_key, prefix, key_hash = generate_api_key()
        assert verify_api_key("", key_hash) is False