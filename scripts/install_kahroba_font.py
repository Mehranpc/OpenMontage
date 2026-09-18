from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path

EXPECTED_SHA256 = "354d3f6fd8f3a330a766d403beac0a37d3d7378a754067265d766ee1a1cae14d"
ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "remotion-composer" / "public" / "fonts" / "kahroba" / "Kahroba-EB-LC.woff2"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def install(source: Path) -> Path:
    source = source.expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"Kahroba source does not exist: {source}")
    actual = sha256(source)
    if actual != EXPECTED_SHA256:
        raise ValueError(f"Kahroba EB-LC SHA-256 mismatch: expected {EXPECTED_SHA256}, got {actual}")
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, TARGET)
    if sha256(TARGET) != EXPECTED_SHA256:
        raise ValueError("installed Kahroba bytes failed post-copy verification")
    return TARGET


def main() -> int:
    parser = argparse.ArgumentParser(description="Install the licensed Kahroba EB-LC runtime font")
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    try:
        target = install(args.source)
    except ValueError as exc:
        parser.error(str(exc))
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
