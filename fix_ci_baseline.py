from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    ".github/workflows/ci.yml",
    """      - name: Install system dependencies
        run: sudo apt-get update && sudo apt-get install -y ffmpeg

      - name: Install dependencies
        run: make install-dev

      - name: Run lint smoke checks
""",
    """      - name: Set up Node.js
        uses: actions/setup-node@v4
        with:
          node-version: \"22\"
          cache: npm
          cache-dependency-path: remotion-composer/package-lock.json

      - name: Install system dependencies
        run: sudo apt-get update && sudo apt-get install -y ffmpeg

      - name: Install Python dependencies
        run: make install-dev

      - name: Install Remotion dependencies
        working-directory: remotion-composer
        run: npm ci

      - name: Run lint smoke checks
""",
)

replace_once(
    "tests/contracts/test_persian_geometry_parity.py",
    """        import json as _json

        edit_path = REPO_ROOT / \"projects\" / \"coffee-hormones-fa\" / \"artifacts\" / \"edit_decisions.json\"
        edit = _json.loads(edit_path.read_text(encoding=\"utf-8\"))
        first = edit[\"persian\"][\"moments\"][0]
        assert first[\"kind\"] == \"hook\"
        assert first[\"id\"] == \"moment-1\"

        built = build_moments([first])
""",
    """        # Keep the structural contract in source control. `projects/` is a
        # generated, gitignored workspace and can never be a CI fixture.
        first = {
            \"id\": \"moment-1\",
            \"kind\": \"hook\",
            \"startSeconds\": 0.4,
            \"endSeconds\": 4.4,
            \"segments\": [
                {\"role\": \"hero\", \"text\": \"هر اضطرابی نشانهٔ خطر نیست\"},
                {\"role\": \"tail\", \"text\": \"گاهی بدن فقط آماده می‌شود\"},
            ],
        }

        built = build_moments([first])
        assert built[0].id == \"moment-1\"
        assert built[0].kind == \"hook\"
""",
)

replace_once(
    "tests/tools/test_hyperframes_compose.py",
    """from tools.video.video_compose import VideoCompose


# ------------------------------------------------------------------
# Tool contract
""",
    """from tools.video.video_compose import VideoCompose


def _force_runtime_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    \"\"\"Make runtime-policy tests independent of the CI host's Node install.\"\"\"
    monkeypatch.setattr(
        HyperFramesCompose,
        \"_node_major_version\",
        classmethod(lambda cls: cls._NODE_FLOOR_MAJOR),
    )
    monkeypatch.setattr(
        \"tools.video.hyperframes_compose.shutil.which\",
        lambda command: f\"/mock/bin/{command}\",
    )


# ------------------------------------------------------------------
# Tool contract
""",
)

replace_once(
    "tests/tools/test_hyperframes_compose.py",
    """    # Clear process cache and force _resolve_npm_package to return a 404.
    monkeypatch.setattr(
""",
    """    _force_runtime_floor(monkeypatch)
    # Clear process cache and force _resolve_npm_package to return a 404.
    monkeypatch.setattr(
""",
)

replace_once(
    "tests/tools/test_hyperframes_compose.py",
    """def test_runtime_check_succeeds_when_npm_resolves(monkeypatch):
    monkeypatch.setattr(
""",
    """def test_runtime_check_succeeds_when_npm_resolves(monkeypatch):
    _force_runtime_floor(monkeypatch)
    monkeypatch.setattr(
""",
)

replace_once(
    "tests/tools/test_hyperframes_compose.py",
    """    # Local binaries must still pass for this to go green.
    if rc[\"node_major\"] is None or not rc[\"ffmpeg_available\"] or not rc[\"npx_available\"]:
        pytest.skip(\"Local runtime floor not met on this machine\")
    assert rc[\"runtime_available\"] is True
""",
    """    assert rc[\"runtime_available\"] is True
""",
)

replace_once(
    "tests/tools/test_hyperframes_compose.py",
    """def test_runtime_check_fails_when_published_cli_crashes(monkeypatch):
    monkeypatch.setattr(
""",
    """def test_runtime_check_fails_when_published_cli_crashes(monkeypatch):
    _force_runtime_floor(monkeypatch)
    monkeypatch.setattr(
""",
)

replace_once(
    "tests/tools/test_hyperframes_compose.py",
    """    if rc[\"node_major\"] is None or not rc[\"ffmpeg_available\"] or not rc[\"npx_available\"]:
        pytest.skip(\"Local runtime floor not met on this machine\")
    assert rc[\"runtime_available\"] is False
""",
    """    assert rc[\"runtime_available\"] is False
""",
)

replace_once(
    "tests/tools/test_persian_default_film_type.py",
    """    def test_quiet_editorial_still_resolves(
        self, clip: Path, staging: Path
    ) -> None:
        props, _ = _build(
            _persian(
                clip,
                design={
                    \"version\": 2,
                    \"profile\": \"quiet-editorial\",
                    \"seed\": \"frozen\",
                },
            ),
            staging,
        )
        assert props[\"design\"][\"profile\"] == \"quiet-editorial\"
""",
    """    def test_quiet_editorial_still_resolves(
        self, clip: Path, staging: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # This is a routing unit test, so provide the loaded-font bridge result
        # explicitly instead of depending on an optional native canvas package.
        measurement = {\"widthPx\": 216.0, \"heightPx\": 54.0}

        def measured_bridge(built, *args, **kwargs):
            for moment in built:
                object.__setattr__(moment, \"stack_height_px\", 180.0)
                object.__setattr__(moment, \"stack_width_px\", 420.0)
                object.__setattr__(
                    moment,
                    \"layout_geometry\",
                    {\"x\": 0.30, \"y\": 0.40, \"w\": 0.39, \"h\": 0.10},
                )
            return measurement

        monkeypatch.setattr(
            \"tools.video.persian_compose._maybe_attach_stack_heights\",
            measured_bridge,
        )
        props, _ = _build(
            _persian(
                clip,
                design={
                    \"version\": 2,
                    \"profile\": \"quiet-editorial\",
                    \"seed\": \"frozen\",
                },
            ),
            staging,
        )
        assert props[\"design\"][\"profile\"] == \"quiet-editorial\"
        assert props[\"watermarkMeasurement\"] == measurement
        assert props[\"watermarkPlan\"]
""",
)

print("patched CI baseline fixtures and runtime assumptions")

# Trigger materialization after the exact patch passed the full verification matrix.
