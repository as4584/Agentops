#!/usr/bin/env python3
"""
TP-Link Archer C2300 / A2300 backup config decoder/encoder.

Decodes the encrypted .bin backup → .xml (readable config).
Encodes modified .xml → .bin (uploadable to router).

Based on https://github.com/acc-/tplink-archer-c2300
Ported to pure Python (no openssl CLI dependency).
"""

from __future__ import annotations

import hashlib
import sys
import zlib
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# AES-256-CBC key and IV (hardcoded in TP-Link firmware)
AES_KEY = bytes.fromhex(
    "2EB38F7EC41D4B8E1422805BCD5F740BC3B95BE163E39D67579EB344427F7836"
)
AES_IV = bytes.fromhex("360028C9064242F81074F4C127D299F6")

# Product name used for MD5 verification
PRODUCT_NAME = "Archer C2300"


def _aes_decrypt(data: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(AES_KEY), modes.CBC(AES_IV))
    dec = cipher.decryptor()
    raw = dec.update(data) + dec.finalize()
    # PKCS7 unpad
    pad_len = raw[-1]
    if 1 <= pad_len <= 16 and all(b == pad_len for b in raw[-pad_len:]):
        raw = raw[:-pad_len]
    return raw


def _aes_encrypt(data: bytes) -> bytes:
    # PKCS7 pad
    pad_len = 16 - (len(data) % 16)
    data = data + bytes([pad_len] * pad_len)
    cipher = Cipher(algorithms.AES(AES_KEY), modes.CBC(AES_IV))
    enc = cipher.encryptor()
    return enc.update(data) + enc.finalize()


def bin_to_xml(bin_path: str, xml_path: str | None = None) -> str:
    """Decrypt .bin → .xml. Returns the output path."""
    bp = Path(bin_path)
    xp = Path(xml_path) if xml_path else bp.with_suffix(".xml")

    encrypted = bp.read_bytes()

    # Layer 1: AES decrypt + zlib decompress → mid.bin
    mid = zlib.decompress(_aes_decrypt(encrypted))

    # First 16 bytes = MD5 of product name
    file_md5 = mid[:16].hex()
    our_md5 = hashlib.md5(PRODUCT_NAME.encode()).hexdigest()

    if file_md5 == our_md5:
        print(f"✓ MD5 matches — this is an {PRODUCT_NAME} backup")
    else:
        print(f"⚠ MD5 mismatch: file={file_md5}, expected={our_md5}")
        print("  Proceeding anyway — file may be from A2300 variant")

    # Skip 16-byte MD5 header → orig.bin
    orig = mid[16:]

    # Layer 2: AES decrypt + zlib decompress → raw XML
    xml_data = zlib.decompress(_aes_decrypt(orig))

    xp.write_bytes(xml_data)
    print(f"✓ XML saved to {xp} ({len(xml_data)} bytes)")
    return str(xp)


def xml_to_bin(xml_path: str, bin_path: str | None = None) -> str:
    """Encrypt .xml → .bin. Returns the output path."""
    xp = Path(xml_path)
    bp = Path(bin_path) if bin_path else xp.with_suffix(".bin")

    xml_data = xp.read_bytes()

    # Layer 2: zlib compress + AES encrypt → orig.bin
    orig = _aes_encrypt(zlib.compress(xml_data))

    # Prepend 16-byte MD5 of product name
    our_md5 = bytes.fromhex(hashlib.md5(PRODUCT_NAME.encode()).hexdigest())
    mid = our_md5 + orig

    # Layer 1: zlib compress + AES encrypt → final .bin
    encrypted = _aes_encrypt(zlib.compress(mid))

    bp.write_bytes(encrypted)
    print(f"✓ BIN saved to {bp} ({len(encrypted)} bytes)")
    return str(bp)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage:")
        print("  Decode: python tplink_config.py decode backup.bin [output.xml]")
        print("  Encode: python tplink_config.py encode config.xml [output.bin]")
        sys.exit(1)

    cmd = sys.argv[1]
    src = sys.argv[2]
    dst = sys.argv[3] if len(sys.argv) > 3 else None

    if cmd == "decode":
        bin_to_xml(src, dst)
    elif cmd == "encode":
        xml_to_bin(src, dst)
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
