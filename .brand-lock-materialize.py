from __future__ import annotations

import hashlib
import py_compile
import subprocess
from pathlib import Path

EXPECTED_GENERATOR_SHA = "3ff30db8eca9357db1149545930212b051fbce4c0d4c50e6a77004c10a349188"
EXPECTED_PATCHED_SHA = "4d412de353e2f254dfa04eb47e929172d924bad8a2e3626594a820e31a470300"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one match in {path}, got {count}: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


generator_path = Path(".brand-lock-generator.py")
source = generator_path.read_text(encoding="utf-8")
actual_sha = hashlib.sha256(source.encode("utf-8")).hexdigest()
if actual_sha != EXPECTED_GENERATOR_SHA:
    raise RuntimeError(
        f"generator SHA mismatch: expected {EXPECTED_GENERATOR_SHA}, got {actual_sha}"
    )

start_marker = (
    'replace_once(\n'
    '    "remotion-composer/src/persian/types.ts",\n'
    "    '''  for (const [index, segment] of moment.segments.entries()) {\n"
)
end_marker = (
    '\nreplace_once(\n'
    '    "remotion-composer/src/persian/filmType/layout.ts",'
)
if source.count(start_marker) != 1:
    raise RuntimeError(
        f"expected one ambiguous TypeScript patch block, got {source.count(start_marker)}"
    )
start = source.index(start_marker)
end = source.index(end_marker, start)
replacement = """replace_once(
    "remotion-composer/src/persian/types.ts",
    '''  if (sources.length === 1 && moment.segments[moment.segments.length - 1].role !== "source") {
    throw new Error(
      `${where}: a 'source' segment must be last. It is a citation appended to ` +
        `the phrase, not a part of it, so anywhere else it interrupts the sentence.`,
    );
  }

  for (const [index, segment] of moment.segments.entries()) {
''',
    '''  if (sources.length === 1 && moment.segments[moment.segments.length - 1].role !== "source") {
    throw new Error(
      `${where}: a 'source' segment must be last. It is a citation appended to ` +
        `the phrase, not a part of it, so anywhere else it interrupts the sentence.`,
    );
  }

  if (moment.exactText) {
    const displayText = moment.segments
      .filter((segment) => segment.role !== "source")
      .map((segment) => segment.text)
      .join(" ");
    if (
      moment.exactText.encoding !== "utf-8" ||
      moment.exactText.normalization !== "none" ||
      displayText !== moment.exactText.text
    ) {
      throw new Error(
        `${where}: exactText does not equal the displayed segments byte-for-byte; ` +
          `strict punctuation, code points, whitespace, and digits may not be normalized.`,
      );
    }
  }

  for (const [index, segment] of moment.segments.entries()) {
''',
)
"""
patched = source[:start] + replacement + source[end:]
patched_sha = hashlib.sha256(patched.encode("utf-8")).hexdigest()
if patched_sha != EXPECTED_PATCHED_SHA:
    raise RuntimeError(
        f"patched generator SHA mismatch: expected {EXPECTED_PATCHED_SHA}, got {patched_sha}"
    )
compile(patched, "/tmp/apply_brand_exact_lock.py", "exec")

# Prevent the generator's deliberate repository-wide legacy-handle replacement
# from rewriting its own source or stale diagnostics.
generator_path.unlink()
Path(".brand-lock-diagnostics.txt").unlink(missing_ok=True)
exec(compile(patched, "/tmp/apply_brand_exact_lock.py", "exec"), {"__name__": "__main__"})

brand_tests = Path("tests/lib/test_persian_brand.py")
replace_once(
    brand_tests,
    '    assert "Pathway_of_Surrender" not in typescript\n',
    '    assert "@Pathway_of_Surrender" not in typescript\n',
)
replace_once(
    brand_tests,
    '''    [
        {"persianText": "روایتِ روشن", "latinText": "OpenMontage"},
''',
    '''    [
        {"persianText": "", "latinText": ""},
        {"persianText": "روایتِ روشن", "latinText": "OpenMontage"},
''',
)
replace_once(
    brand_tests,
    '''    requested["overrideAuthorization"] = {**_authorization(), "decisionId": ""}
    with pytest.raises(BrandAuthorizationError, match="decisionId"):
        resolve_watermark(requested)
''',
    '''    requested["overrideAuthorization"] = {**_authorization(), "decisionId": ""}
    with pytest.raises(BrandAuthorizationError, match="decisionId"):
        resolve_watermark(requested)
    requested["overrideAuthorization"] = {**_authorization(), "reason": ""}
    with pytest.raises(BrandAuthorizationError, match="reason"):
        resolve_watermark(requested)
''',
)

for file_name in (
    "lib/persian_brand.py",
    "lib/persian_moments.py",
    "tools/video/persian_compose.py",
    "tests/lib/test_persian_brand.py",
    "tests/lib/test_persian_film_type.py",
):
    py_compile.compile(file_name, doraise=True)

# Remove every bootstrap/materialization artifact before the implementation commit.
for file_name in (
    "brand-lock.b64.part-0",
    "brand-lock.b64.part-1",
    "brand-lock.b64.part-2",
    ".brand-lock-generator.py",
    ".brand-lock-diagnostics.txt",
    ".brand-lock-materialization.txt",
    ".brand-lock-verification.txt",
    ".brand-lock-materialize.py",
    ".github/workflows/materialize-brand-exact-lock.yml",
):
    Path(file_name).unlink(missing_ok=True)

subprocess.run(["git", "diff", "--check"], check=True)
print(f"generator_original_sha={actual_sha}")
print(f"generator_patched_sha={patched_sha}")
print("materialization_result=success")
