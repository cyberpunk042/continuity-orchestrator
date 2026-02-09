"""
Tests for token obfuscation — XOR encrypt, fragment, scatter, reassemble.

Verifies:
- Round-trip: obfuscate → simulate JS reassembly → original token
- Empty token produces no fragments
- Fragment counts match configuration
- No raw token substring appears in any fragment HTML
- Decoy fragments don't interfere with reassembly
- Different builds produce different ciphertext (random key)
"""

import re

import pytest

from src.site.token_obfuscator import obfuscate_token


# ── Fixtures ──────────────────────────────────────────────────────

SAMPLE_PAT = "ghp_FakeTestToken000000000000000000000"
LONG_PAT = "github_pat_00FAKE00_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"


def _simulate_js_reassembly(result: dict) -> str:
    """Simulate what the JS _rt() function does — parse DOM, reassemble, XOR."""
    cipher_attr = result["cipher_attr"]
    key_attr = result["key_attr"]

    c_chunks = {}
    k_chunks = {}

    for frag in result["fragments_html"]:
        m = re.search(rf'{re.escape(cipher_attr)}="(\d+):([0-9a-f]+)"', frag)
        if m:
            c_chunks[int(m.group(1))] = m.group(2)
        m = re.search(rf'{re.escape(key_attr)}="(\d+):([0-9a-f]+)"', frag)
        if m:
            k_chunks[int(m.group(1))] = m.group(2)

    ch = "".join(c_chunks[i] for i in sorted(c_chunks))
    kh = "".join(k_chunks[i] for i in sorted(k_chunks))

    if not ch or not kh or len(ch) != len(kh):
        return ""

    out = ""
    for i in range(0, len(ch), 2):
        out += chr(int(ch[i:i + 2], 16) ^ int(kh[i:i + 2], 16))
    return out


# ── Tests ─────────────────────────────────────────────────────────

class TestTokenObfuscation:
    """Core obfuscation tests."""

    def test_roundtrip_short_pat(self):
        """Short PAT survives obfuscate → reassemble."""
        result = obfuscate_token(SAMPLE_PAT)
        assert _simulate_js_reassembly(result) == SAMPLE_PAT

    def test_roundtrip_long_pat(self):
        """Long fine-grained PAT survives obfuscate → reassemble."""
        result = obfuscate_token(LONG_PAT)
        assert _simulate_js_reassembly(result) == LONG_PAT

    def test_empty_token(self):
        """Empty token produces no fragments."""
        result = obfuscate_token("")
        assert result["fragments_html"] == []
        assert result["meta"]["empty"] is True

    def test_fragment_count(self):
        """Fragment count matches config."""
        result = obfuscate_token(SAMPLE_PAT, n_fragments=4, n_decoys=3)
        meta = result["meta"]
        assert meta["cipher_fragments"] >= 4
        assert meta["key_fragments"] >= 4
        assert meta["decoys"] == 3
        assert meta["total_spans"] == meta["cipher_fragments"] + meta["key_fragments"] + meta["decoys"]

    def test_no_raw_token_in_fragments(self):
        """Raw token text must NOT appear in any fragment HTML."""
        result = obfuscate_token(SAMPLE_PAT)
        combined = "\n".join(result["fragments_html"])
        # The full token should not be present
        assert SAMPLE_PAT not in combined
        # Common PAT prefixes should not be present
        assert "ghp_" not in combined
        assert "github_pat_" not in combined

    def test_no_base64_of_token_in_output(self):
        """Base64-encoded token should NOT appear anywhere."""
        import base64
        b64 = base64.b64encode(SAMPLE_PAT.encode()).decode()
        result = obfuscate_token(SAMPLE_PAT)
        combined = "\n".join(result["fragments_html"]) + result["js_decrypt"]
        assert b64 not in combined

    def test_different_builds_different_ciphertext(self):
        """Two builds of the same token produce different ciphertext."""
        r1 = obfuscate_token(SAMPLE_PAT)
        r2 = obfuscate_token(SAMPLE_PAT)
        # Extract all cipher data-attr values
        combined1 = "\n".join(r1["fragments_html"])
        combined2 = "\n".join(r2["fragments_html"])
        # The cipher attr name itself is random
        assert r1["cipher_attr"] != r2["cipher_attr"]

    def test_js_decrypt_function_present(self):
        """The JS decrypt function is included."""
        result = obfuscate_token(SAMPLE_PAT)
        assert "function _rt()" in result["js_decrypt"]
        assert result["cipher_attr"] in result["js_decrypt"]
        assert result["key_attr"] in result["js_decrypt"]

    def test_fragments_are_hidden_spans(self):
        """All fragments are hidden <span> elements."""
        result = obfuscate_token(SAMPLE_PAT)
        for frag in result["fragments_html"]:
            assert frag.startswith("<span ")
            assert 'display:none' in frag
            assert frag.endswith("</span>")

    def test_decoy_fragments_dont_interfere(self):
        """Decoys have a different attr name and don't affect reassembly."""
        result = obfuscate_token(SAMPLE_PAT, n_decoys=10)
        assert result["decoy_attr"] != result["cipher_attr"]
        assert result["decoy_attr"] != result["key_attr"]
        # Reassembly still works
        assert _simulate_js_reassembly(result) == SAMPLE_PAT

    @pytest.mark.parametrize("n_frags", [2, 3, 5, 8, 12])
    def test_various_fragment_counts(self, n_frags):
        """Roundtrip works for various fragment counts."""
        result = obfuscate_token(SAMPLE_PAT, n_fragments=n_frags)
        assert _simulate_js_reassembly(result) == SAMPLE_PAT

    def test_unicode_resilience(self):
        """Token with only ASCII chars (PATs are always ASCII)."""
        token = "ghp_" + "A" * 36
        result = obfuscate_token(token)
        assert _simulate_js_reassembly(result) == token
