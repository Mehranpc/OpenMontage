"""Geometry and attribute audit for a finished Film Type render.

Companion to :mod:`lib.persian_render_qa`. That module answers "does this
video contain a dead stretch" by measuring luminance. This one answers the
questions a reviewer previously re-derived by hand after every render:

* does every text and watermark rectangle actually sit inside the safe area,
  and by what margin;
* what ``strength`` / ``fieldPeakAlpha`` / ``subjectSafety`` did each moment
  resolve to;
* do the painted field attributes in the rendered markup match the profile
  that was actually resolved.

The last point is the reason this module exists. Opening ``components.tsx``
and reasoning about which version branch *should* have run is not
verification -- that is precisely how 2.9 shipped falling through to the
legacy painter. So :func:`audit_rendered_attributes` takes markup produced by
the browser, never a source path.

Nothing here changes a pixel. It only reports what a finished render did.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: A rectangle clearing its boundary by less than this fraction of the frame
#: is reported as tight. Not a failure -- it is legal -- but a 0.5% margin is
#: one font change away from a violation, and the reviewer must see that
#: before it becomes a violation, not after.
TIGHT_MARGIN_WARN = 0.02

_SHAPE_RE = re.compile(r'data-film-field-shape="([^"]+)"')
_SCOPE_RE = re.compile(r'data-film-field-scope="([^"]+)"')


def safe_area_bounds(safe: dict[str, Any]) -> tuple[float, float, float, float]:
    """Return ``(left, top, right, bottom)`` insets for a safe-area block.

    ``left``/``right`` fall back to the symmetric ``side`` value, matching
    ``inSafe`` in ``layout.ts``. Reels uses asymmetric sides, so guessing
    symmetry here would silently pass a rectangle the renderer rejects.
    """
    side = float(safe.get("side", 0.0))
    return (
        float(safe.get("left", side)),
        float(safe["top"]),
        float(safe.get("right", side)),
        float(safe["bottom"]),
    )


@dataclass
class RectAudit:
    """One rectangle measured against the safe area that governs it."""

    label: str
    rect: dict[str, float]
    margins: dict[str, float]

    @property
    def inside(self) -> bool:
        return all(margin >= -1e-8 for margin in self.margins.values())

    @property
    def worst_edge(self) -> str:
        return min(self.margins, key=lambda edge: self.margins[edge])

    @property
    def worst_margin(self) -> float:
        return self.margins[self.worst_edge]

    @property
    def tight(self) -> bool:
        return self.inside and self.worst_margin < TIGHT_MARGIN_WARN

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "rect": {key: round(float(value), 5) for key, value in self.rect.items()},
            "margins": {edge: round(value, 5) for edge, value in self.margins.items()},
            "inside": self.inside,
            "tight": self.tight,
            "worstEdge": self.worst_edge,
            "worstMargin": round(self.worst_margin, 5),
        }


def audit_rect(rect: dict[str, Any], safe: dict[str, Any], *, label: str) -> RectAudit:
    """Measure one normalized rectangle against one safe area."""
    left, top, right, bottom = safe_area_bounds(safe)
    x, y = float(rect["x"]), float(rect["y"])
    w, h = float(rect["w"]), float(rect["h"])
    return RectAudit(
        label=label,
        rect={"x": x, "y": y, "w": w, "h": h},
        margins={
            "left": x - left,
            "top": y - top,
            "right": (1.0 - right) - (x + w),
            "bottom": (1.0 - bottom) - (y + h),
        },
    )


def expected_field_attributes(profile: dict[str, Any]) -> dict[str, str]:
    """What the painted field attributes must be for this resolved profile.

    Derived from the tokens that will actually be painted, so a profile that
    turns ``perRow`` off is checked against ``block`` rather than against a
    remembered expectation.
    """
    diffuse = (profile.get("contrast") or {}).get("diffuseField")
    if not isinstance(diffuse, dict):
        raise ValueError(
            "this profile paints no diffuse field, so field attributes cannot "
            "be predicted; audit the profile that was actually resolved."
        )
    return {
        "shape": "diffuse",
        "scope": "row" if diffuse.get("perRow") else "block",
    }


def audit_rendered_attributes(
    markup: str, *, expected: dict[str, str]
) -> dict[str, Any]:
    """Compare field attributes in RENDERED markup against `expected`.

    `markup` must come from the browser that painted -- a prepass DOM dump or
    a captured composition -- never from reading the component source.
    """
    shapes = sorted(set(_SHAPE_RE.findall(markup)))
    scopes = sorted(set(_SCOPE_RE.findall(markup)))
    problems: list[str] = []
    if not shapes:
        problems.append(
            "no data-film-field-shape attribute is present in the rendered "
            "markup; the field may have fallen through to a painter that does "
            "not emit it."
        )
    if shapes not in ([], [expected["shape"]]):
        problems.append(
            f"rendered field shape {shapes} does not match the resolved "
            f"profile's {expected['shape']!r}."
        )
    if scopes not in ([], [expected["scope"]]):
        problems.append(
            f"rendered field scope {scopes} does not match the resolved "
            f"profile's {expected['scope']!r}."
        )
    return {
        "expected": dict(expected),
        "shapes": shapes,
        "scopes": scopes,
        "passed": not problems,
        "problems": problems,
    }


@dataclass
class GeometryAudit:
    """The geometry verdict over one finished render's props sidecar."""

    profile_version: str
    layout_version: int
    content_hash: str
    moments: list[dict[str, Any]] = field(default_factory=list)
    text_rects: list[RectAudit] = field(default_factory=list)
    watermark_rects: list[RectAudit] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def all_rects(self) -> list[RectAudit]:
        return [*self.text_rects, *self.watermark_rects]

    @property
    def violations(self) -> list[RectAudit]:
        return [audit for audit in self.all_rects if not audit.inside]

    @property
    def tight(self) -> list[RectAudit]:
        return [audit for audit in self.all_rects if audit.tight]

    @property
    def passed(self) -> bool:
        return not self.violations

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "profileVersion": self.profile_version,
            "layoutVersion": self.layout_version,
            "contentHash": self.content_hash,
            "moments": self.moments,
            "textRects": [audit.to_dict() for audit in self.text_rects],
            "watermarkRects": [audit.to_dict() for audit in self.watermark_rects],
            "violations": [audit.to_dict() for audit in self.violations],
            "tight": [audit.to_dict() for audit in self.tight],
            "warnings": list(self.warnings),
        }

    def report_lines(self) -> list[str]:
        """A stable, paste-able reviewer report."""
        lines = [
            f"profile {self.profile_version} (layoutVersion {self.layout_version})",
            f"contentHash {self.content_hash}",
            "",
            "moments:",
        ]
        for moment in self.moments:
            rect = moment["rect"]
            lines.append(
                f"  {moment['id']}: strength={moment['strength']} "
                f"fieldPeakAlpha={moment['fieldPeakAlpha']} "
                f"subjectSafety={moment['subjectSafety']} "
                f"rect=x{rect['x']} y{rect['y']} w{rect['w']} h{rect['h']}"
            )
        lines += ["", "safe area:"]
        for audit in self.all_rects:
            state = (
                "OUTSIDE" if not audit.inside else "tight" if audit.tight else "ok"
            )
            lines.append(
                f"  {audit.label}: {state} "
                f"(closest {audit.worst_edge} {audit.worst_margin:+.5f})"
            )
        lines += ["", f"warnings: {len(self.warnings)}"]
        lines += [f"  {index}. {text}" for index, text in enumerate(self.warnings, 1)]
        return lines


def audit_props(props: dict[str, Any]) -> GeometryAudit:
    """Audit a rendered props sidecar (``*.mp4.props.json``).

    Reads only what the render itself recorded, so the report describes the
    render that exists rather than the profile currently on disk.
    """
    design = props.get("design") or {}
    profile = design.get("resolved") or {}
    film_type = props.get("filmType") or {}
    if not profile or not film_type:
        raise ValueError(
            "these props carry no resolved Film Type design; audit the sidecar "
            "written next to the rendered file."
        )
    fmt = props.get("format", "vertical")
    text_safe = profile["formats"][fmt]["safeArea"]
    watermark_safe = (
        (profile.get("watermark") or {}).get("safeAreas") or {}
    ).get(fmt, text_safe)

    moments: list[dict[str, Any]] = []
    text_rects: list[RectAudit] = []
    for moment_id, layout in (film_type.get("moments") or {}).items():
        rect = layout["rect"]
        moments.append(
            {
                "id": moment_id,
                "strength": layout.get("strength"),
                "fieldPeakAlpha": layout.get("fieldPeakAlpha"),
                "subjectSafety": layout.get("subjectSafety"),
                "placement": layout.get("placement"),
                "rect": {key: round(float(rect[key]), 5) for key in ("x", "y", "w", "h")},
            }
        )
        text_rects.append(audit_rect(rect, text_safe, label=f"text {moment_id}"))

    watermark_rects = [
        audit_rect(
            slot["rect"],
            watermark_safe,
            label=f"watermark {slot.get('zone', '?')} "
            f"{slot.get('startSeconds', 0)}-{slot.get('endSeconds', 0)}s",
        )
        for slot in (props.get("watermarkPlan") or [])
    ]

    return GeometryAudit(
        profile_version=profile.get("profileVersion", ""),
        layout_version=int(profile.get("layoutVersion", 0)),
        content_hash=design.get("contentHash", ""),
        moments=sorted(moments, key=lambda item: item["id"]),
        text_rects=text_rects,
        watermark_rects=watermark_rects,
        warnings=list(film_type.get("warnings") or []),
    )


def audit_props_file(path: Path) -> GeometryAudit:
    """Audit the props sidecar at `path`."""
    return audit_props(json.loads(Path(path).read_text(encoding="utf-8")))


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(
            "usage: python -m lib.persian_render_geometry <render>.mp4.props.json",
            file=sys.stderr,
        )
        return 2
    audit = audit_props_file(Path(args[0]))
    print("\n".join(audit.report_lines()))
    if audit.violations:
        print("\nFAILED: rectangles outside the safe area.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())
