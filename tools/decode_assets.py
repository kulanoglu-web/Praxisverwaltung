"""Decode validated base64 asset chunks before the PyInstaller build."""
from __future__ import annotations
import base64
import hashlib
import sys
from pathlib import Path

EXPECTED = {
    "assets/logo.png": "e8442deacfcdffa942148776975d5e556c34d56ec9d191622565d0ba02c4e9a6",
}

def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def gather_b64(target: str) -> str:
    parts = sorted(Path(".").glob(f"{target}.b64.*"))
    if not parts:
        raise FileNotFoundError(f"Keine Chunks gefunden: {target}.b64.*")
    return "".join(
        p.read_text(encoding="ascii").replace("\r", "").replace("\n", "")
        for p in parts
    )

def decode_one(target: str, expected: str) -> None:
    target_path = Path(target)
    try:
        raw = base64.b64decode(gather_b64(target), validate=True)
    except Exception as e:
        print(f"[FEHLER] Asset-Decode fehlgeschlagen fuer {target}: {e}", file=sys.stderr)
        sys.exit(1)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(raw)
    actual = sha256_of(target_path)
    if actual != expected:
        print(f"[FEHLER] Hash-Mismatch fuer {target}: erwartet={expected} erhalten={actual}", file=sys.stderr)
        try: target_path.unlink()
        except OSError: pass
        sys.exit(1)
    print(f"[OK] {target} size={target_path.stat().st_size} sha256={actual}")

def main() -> None:
    for target, expected in EXPECTED.items():
        decode_one(target, expected)

if __name__ == "__main__":
    main()
