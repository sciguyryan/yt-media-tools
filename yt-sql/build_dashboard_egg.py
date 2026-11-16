"""Regenerate the dashboard easter egg's encrypted briefings.

The briefings shown for the observer's incantations are stored in
``dashboard/egg.js`` as RC4-encrypted, base64-encoded blobs. This utility is
the transparent counterpart to that obfuscation: it reads the plain payload
sources (``dashboard/egg-payload-*.js``), encrypts each with a normalised key,
and rewrites the blob inside ``egg.js``.

The cipher is deliberately public and simple; the key is what is withheld.
Each briefing's key is its own incantation, normalised to lowercase with all
non-alphanumeric characters removed, exactly as the page derives it from the
typed trigger. Changing a payload requires regenerating its blob with the
matching trigger phrase, so the keys and the trigger phrases in ``egg.js``
must stay in step.

Usage:
    python yt-sql/build_dashboard_egg.py            # regenerate both blobs
    python yt-sql/build_dashboard_egg.py --check    # verify blobs match payloads and keys
"""

from __future__ import annotations

import argparse
import base64
import re
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "dashboard"
EGG_PATH = ASSETS / "egg.js"
# One incantation per briefing: (payload source, blob constant, trigger phrase).
# The trigger phrase doubles as the key by design.
BRIEFINGS = (
    ("egg-payload-convergence.js", "CIPHER_CONVERGENCE", "el psy kongroo"),
    ("egg-payload-reading-steiner.js", "CIPHER_READING_STEINER", "reading steiner"),
)


def normalise_key(raw: str) -> bytes:
    """Reduce a key phrase to lowercase ASCII letters and digits."""
    return "".join(character for character in raw.casefold() if character.isalnum()).encode("utf-8")


def rc4(data: bytes, key: bytes) -> bytes:
    """Encrypt or decrypt bytes with RC4; the operation is symmetric."""
    schedule = list(range(256))
    j = 0
    for i in range(256):
        j = (j + schedule[i] + key[i % len(key)]) % 256
        schedule[i], schedule[j] = schedule[j], schedule[i]
    output = bytearray()
    i = j = 0
    for byte in data:
        i = (i + 1) % 256
        j = (j + schedule[i]) % 256
        schedule[i], schedule[j] = schedule[j], schedule[i]
        output.append(byte ^ schedule[(schedule[i] + schedule[j]) % 256])
    return bytes(output)


def encrypt_payload(payload: bytes, key: bytes) -> str:
    return base64.b64encode(rc4(payload, key)).decode("ascii")


def extract_blob(egg_source: str, constant: str) -> str:
    match = re.search(rf'const {constant} = "([^"]*)";', egg_source)
    if not match:
        raise SystemExit(f"egg.js does not contain a {constant} assignment")
    return match.group(1)


def regenerate() -> None:
    egg_source = EGG_PATH.read_text(encoding="utf-8")
    for payload_name, constant, trigger in BRIEFINGS:
        payload = (ASSETS / payload_name).read_bytes()
        blob = encrypt_payload(payload, normalise_key(trigger))
        pattern = re.compile(rf'const {constant} = "([^"]*)";')
        if not pattern.search(egg_source):
            raise SystemExit(f"egg.js does not contain a {constant} assignment")
        egg_source = pattern.sub(f'const {constant} = "{blob}";', egg_source, count=1)
        print(f"Regenerated {constant} ({len(blob)} characters) from {payload_name}.")
    EGG_PATH.write_text(egg_source, encoding="utf-8")


def check() -> bool:
    """Return whether every committed blob decrypts to its committed payload."""
    egg_source = EGG_PATH.read_text(encoding="utf-8")
    for payload_name, constant, trigger in BRIEFINGS:
        payload = (ASSETS / payload_name).read_bytes()
        blob = extract_blob(egg_source, constant)
        if rc4(base64.b64decode(blob), normalise_key(trigger)) != payload:
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="Verify the blobs without rewriting them")
    args = parser.parse_args()
    if args.check:
        current = check()
        print(
            "The committed briefings match the payloads and key."
            if current
            else "The committed briefings do NOT match the payloads and key."
        )
        return 0 if current else 1
    regenerate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
