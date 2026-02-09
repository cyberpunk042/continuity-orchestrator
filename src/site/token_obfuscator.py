"""
Token obfuscation for public site embedding.

Encrypts a secret token using XOR with a random per-build key, then splits
the ciphertext and key into shuffled fragments scattered across hidden DOM
elements. At runtime, JavaScript collects fragments by data-attribute,
reassembles, XOR-decrypts, and recovers the token only in memory.

Security model:
- No raw token or recognisable pattern (ghp_, github_pat_) in page source
- No base64 blob that can be trivially decoded
- Fragments look like random hex, mixed with decoy fragments
- Key is split separately from ciphertext — both must be reassembled
- Casual inspection, Ctrl+F, and automated scanners are defeated
- NOT crypto-grade: a determined reverse-engineer reading the JS can
  still recover the token. This is defence-in-depth, not a vault.
"""

from __future__ import annotations

import os
import random
from typing import Dict, List


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    """XOR data with key (key is cycled if shorter)."""
    return bytes(d ^ key[i % len(key)] for i, d in enumerate(data))


def _split_hex(hex_str: str, n_chunks: int) -> List[str]:
    """Split a hex string into n roughly-equal chunks."""
    chunk_size = max(2, len(hex_str) // n_chunks)
    # Ensure even-length chunks (for hex pairs)
    chunk_size = chunk_size + (chunk_size % 2)
    chunks = []
    for i in range(0, len(hex_str), chunk_size):
        chunk = hex_str[i:i + chunk_size]
        if chunk:
            chunks.append(chunk)
    return chunks


def _random_hex(length: int) -> str:
    """Generate a random hex string of given length."""
    return os.urandom(length // 2 + 1).hex()[:length]


def _random_class_name() -> str:
    """Generate an innocent-looking CSS class name."""
    prefixes = [
        "ui", "el", "nd", "vw", "st", "mt", "pg", "wx", "fn", "bk",
        "ld", "rt", "sc", "gd", "fx", "hd", "tx", "ly", "sp", "cr",
    ]
    suffixes = [
        "data", "meta", "info", "hint", "mark", "note", "flag", "prop",
        "attr", "spec", "conf", "bind", "slot", "item", "cell", "part",
    ]
    return random.choice(prefixes) + "-" + random.choice(suffixes)


def obfuscate_token(
    raw_token: str,
    n_fragments: int = 5,
    n_decoys: int = 4,
) -> Dict:
    """
    Encrypt and fragment a token for safe embedding in public HTML.

    Returns a dict with:
        - fragments_html: list of HTML <span> strings to scatter in DOM
        - cipher_attr: the data attribute name for ciphertext fragments
        - key_attr: the data attribute name for key fragments
        - decoy_attr: the data attribute name for decoy fragments
        - js_decrypt: JavaScript snippet that recovers the token
        - meta: debug info (fragment count, etc.)
    """
    if not raw_token:
        return {
            "fragments_html": [],
            "cipher_attr": "",
            "key_attr": "",
            "decoy_attr": "",
            "js_decrypt": 'function _rt(){return "";}',
            "meta": {"empty": True},
        }

    # 1. Generate random XOR key (same length as token)
    key = os.urandom(len(raw_token))

    # 2. XOR-encrypt
    cipher = _xor_bytes(raw_token.encode("utf-8"), key)
    cipher_hex = cipher.hex()
    key_hex = key.hex()

    # 3. Split into fragments
    cipher_chunks = _split_hex(cipher_hex, n_fragments)
    key_chunks = _split_hex(key_hex, n_fragments)

    # 4. Generate decoy fragments (same length distribution)
    decoy_chunks = []
    for i in range(n_decoys):
        ref = cipher_chunks[i % len(cipher_chunks)]
        decoy_chunks.append(_random_hex(len(ref)))

    # 5. Choose non-obvious attribute names
    # These look like generic UI framework data attributes
    cipher_attr = "data-v-" + _random_hex(6)
    key_attr = "data-v-" + _random_hex(6)
    decoy_attr = "data-v-" + _random_hex(6)

    # 6. Build HTML fragments with order indices
    all_fragments = []

    for i, chunk in enumerate(cipher_chunks):
        cls = _random_class_name()
        all_fragments.append(
            f'<span class="{cls}" {cipher_attr}="{i}:{chunk}" '
            f'style="display:none"></span>'
        )

    for i, chunk in enumerate(key_chunks):
        cls = _random_class_name()
        all_fragments.append(
            f'<span class="{cls}" {key_attr}="{i}:{chunk}" '
            f'style="display:none"></span>'
        )

    for i, chunk in enumerate(decoy_chunks):
        cls = _random_class_name()
        all_fragments.append(
            f'<span class="{cls}" {decoy_attr}="{i}:{chunk}" '
            f'style="display:none"></span>'
        )

    # 7. Shuffle all fragments
    random.shuffle(all_fragments)

    # 8. Build JS reassembly function
    # Minified-ish, with non-obvious variable names
    js_decrypt = f"""
    function _rt() {{
        try {{
            var _c = [], _k = [];
            document.querySelectorAll('[{cipher_attr}]').forEach(function(e) {{
                var p = e.getAttribute('{cipher_attr}').split(':');
                _c[parseInt(p[0])] = p[1];
            }});
            document.querySelectorAll('[{key_attr}]').forEach(function(e) {{
                var p = e.getAttribute('{key_attr}').split(':');
                _k[parseInt(p[0])] = p[1];
            }});
            var ch = _c.join(''), kh = _k.join('');
            if (!ch || !kh || ch.length !== kh.length) return '';
            var out = '';
            for (var i = 0; i < ch.length; i += 2) {{
                out += String.fromCharCode(
                    parseInt(ch.substr(i, 2), 16) ^
                    parseInt(kh.substr(i, 2), 16)
                );
            }}
            return out;
        }} catch(e) {{ return ''; }}
    }}"""

    return {
        "fragments_html": all_fragments,
        "cipher_attr": cipher_attr,
        "key_attr": key_attr,
        "decoy_attr": decoy_attr,
        "js_decrypt": js_decrypt,
        "meta": {
            "cipher_fragments": len(cipher_chunks),
            "key_fragments": len(key_chunks),
            "decoys": len(decoy_chunks),
            "total_spans": len(all_fragments),
        },
    }
