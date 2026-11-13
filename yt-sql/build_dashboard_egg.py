"""Regenerate the dashboard easter egg's encrypted briefing.

The briefing shown for the observer's incantation is stored in
``dashboard/egg.js`` as an RC4-encrypted, base64-encoded blob. This utility is
the transparent counterpart to that obfuscation: it reads the plain payload
source (``dashboard/egg-payload.js``), encrypts it with a normalised key, and
rewrites the blob inside ``egg.js``.

The cipher is deliberately public and simple; the key is what is withheld. The
key is the incantation itself, normalised to lowercase with all
non-alphanumeric characters removed. Passing a different key via ``--key``
regenerates a blob that the page can no longer decrypt, so only change the key
together with the trigger phrase in ``egg.js``.

Usage:
    python yt-sql/build_dashboard_egg.py            # regenerate the blob
    python yt-sql/build_dashboard_egg.py --check    # verify blob matches payload and key
"""

from __future__ import annotations

import argparse
import base64
import re
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "dashboard"
PAYLOAD_PATH = ASSETS / "egg-payload.js"
EGG_PATH = ASSETS / "egg.js"
BLOB_PATTERN = re.compile(r'const CIPHER_BLOB = "([^"]*)";')
TRIGGER_PATTERN = re.compile(r'const TRIGGER = "([^"]*)";')


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


def extract_blob(egg_source: str) -> str:
    match = BLOB_PATTERN.search(egg_source)
    if not match:
        raise SystemExit("egg.js does not contain a CIPHER_BLOB assignment")
    return match.group(1)


def default_key(egg_source: str) -> bytes:
    """The trigger phrase is the key by design; extract and normalise it."""
    match = TRIGGER_PATTERN.search(egg_source)
    if not match:
        raise SystemExit("egg.js does not contain a TRIGGER assignment")
    return normalise_key(match.group(1))


def regenerate(key: bytes) -> None:
    payload = PAYLOAD_PATH.read_bytes()
    egg_source = EGG_PATH.read_text(encoding="utf-8")
    blob = encrypt_payload(payload, key)
    updated = BLOB_PATTERN.sub(f'const CIPHER_BLOB = "{blob}";', egg_source, count=1)
    EGG_PATH.write_text(updated, encoding="utf-8")
    print(f"Regenerated CIPHER_BLOB ({len(blob)} characters) from {PAYLOAD_PATH.name}.")


def check(key: bytes) -> bool:
    """Return whether the committed blob decrypts to the committed payload."""
    egg_source = EGG_PATH.read_text(encoding="utf-8")
    payload = PAYLOAD_PATH.read_bytes()
    return rc4(base64.b64decode(extract_blob(egg_source)), key) == payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--key", help="Key phrase; defaults to the trigger phrase in egg.js, normalised")
    parser.add_argument("--check", action="store_true", help="Verify the blob without rewriting it")
    args = parser.parse_args()
    key = normalise_key(args.key) if args.key else default_key(EGG_PATH.read_text(encoding="utf-8"))
    if args.check:
        current = check(key)
        print(
            "The committed briefing matches the payload and key."
            if current
            else "The committed briefing does NOT match the payload and key."
        )
        return 0 if current else 1
    regenerate(key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
