"""Direct clip search: lightweight provider-agnostic stock footage acquisition.

This tool replaces the heavy corpus_builder → clip_search pipeline when
you already know what you want and just need clips downloaded fast. It
uses the same StockSource adapter protocol (Pexels, Archive.org, NASA,
Wikimedia, Unsplash, ...) but skips CLIP embeddings, motion scoring,
index.jsonl, and .npy files entirely.

When to use this instead of corpus_builder
------------------------------------------
- You have a shot list and know the queries for each slot.
- You want clips downloaded in minutes, not tens of minutes.
- You plan to inspect thumbnails yourself (or via a sub-agent) rather
  than relying on CLIP similarity ranking.
- You are doing act-by-act production and can reuse clips across acts
  by pointing at previously downloaded directories.

When to use corpus_builder instead
----------------------------------
- You need CLIP-based semantic ranking (clip_search.rank_for_slot).
- You have 50+ slots and want automated diversification.
- The visual match between query text and actual footage matters more
  than speed.

What it does per query
----------------------
1. Fan out across all available (or specified) StockSource adapters.
2. Download up to `clips_per_query` clips per query.
3. Extract one thumbnail per clip via ffmpeg (for visual inspection).
4. Return full metadata: paths, durations, sources, thumbnails.

No CLIP model. No embeddings. No corpus index. Just files on disk.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import subprocess
import time
import urllib.parse
from pathlib import Path
from typing import Any, Optional

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)


class _DeadlineExceeded(TimeoutError):
    """Raised when the direct-clip-search wall-clock deadline is exhausted."""


_MIB = 1024 * 1024
_DEFAULT_MAX_BYTES_PER_CLIP = 96 * _MIB
_DEFAULT_MAX_TOTAL_DOWNLOAD_BYTES = 512 * _MIB
_DEFAULT_MAX_CANDIDATES_TOTAL = 24
_FFPROBE_VALIDATION_TIMEOUT_SECONDS = 15.0


class _DownloadQuotaExceeded(RuntimeError):
    """Raised before an acquisition can exceed a configured byte ceiling."""

    def __init__(self, message: str, *, scope: str) -> None:
        super().__init__(message)
        self.scope = scope


class _MediaValidationError(ValueError):
    """Raised when downloaded bytes do not satisfy the requested media filters."""


class _DownloadBudget:
    """Counts streamed network bytes for one invocation and its current clip."""

    def __init__(self, *, max_bytes_per_clip: int, max_total_bytes: int) -> None:
        if max_bytes_per_clip <= 0 or max_total_bytes <= 0:
            raise ValueError("download byte limits must be positive")
        if max_bytes_per_clip > max_total_bytes:
            raise ValueError("max_bytes_per_clip cannot exceed max_total_download_bytes")
        self.max_bytes_per_clip = max_bytes_per_clip
        self.max_total_bytes = max_total_bytes
        self.total_bytes = 0
        self.clip_bytes = 0

    def start_clip(self) -> None:
        self.clip_bytes = 0

    def preflight_content_length(self, raw_value: Any) -> None:
        if raw_value in (None, ""):
            return
        try:
            declared = int(raw_value)
        except (TypeError, ValueError):
            return
        if declared < 0:
            return
        if declared > self.max_bytes_per_clip:
            raise _DownloadQuotaExceeded(
                f"server declared {declared} bytes for one clip; limit is "
                f"{self.max_bytes_per_clip}",
                scope="clip",
            )
        if self.total_bytes + declared > self.max_total_bytes:
            raise _DownloadQuotaExceeded(
                f"server-declared download would exceed invocation limit "
                f"{self.max_total_bytes} bytes",
                scope="total",
            )

    def consume(self, size: int) -> None:
        if size <= 0:
            return
        self.clip_bytes += size
        self.total_bytes += size
        if self.clip_bytes > self.max_bytes_per_clip:
            raise _DownloadQuotaExceeded(
                f"clip exceeded {self.max_bytes_per_clip} bytes while streaming",
                scope="clip",
            )
        if self.total_bytes > self.max_total_bytes:
            raise _DownloadQuotaExceeded(
                f"invocation exceeded {self.max_total_bytes} downloaded bytes",
                scope="total",
            )

    def reconcile_file_size(self, size: int) -> None:
        """Count bytes for adapters that do not consume via iter_content."""
        if size > self.clip_bytes:
            self.consume(size - self.clip_bytes)
        if size > self.max_bytes_per_clip:
            raise _DownloadQuotaExceeded(
                f"downloaded file is {size} bytes; per-clip limit is "
                f"{self.max_bytes_per_clip}",
                scope="clip",
            )


class DirectClipSearch(BaseTool):
    name = "direct_clip_search"
    version = "0.2.0"
    tier = ToolTier.SOURCE
    capability = "clip_acquisition"
    provider = "openmontage"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.HYBRID  # local disk + network APIs

    dependencies = [
        "python:requests",
    ]
    install_instructions = (
        "At least one stock source must be configured:\n"
        "  PEXELS_API_KEY for Pexels (free at https://www.pexels.com/api/)\n"
        "  UNSPLASH_ACCESS_KEY for Unsplash (see https://unsplash.com/documentation)\n"
        "  archive.org, nasa, and wikimedia work without API keys"
    )
    agent_skills = []

    capabilities = [
        "multi_source_search",
        "clip_download",
        "thumbnail_extraction",
    ]
    supports = {
        "multi_source": True,
        "video_and_image": True,
        "provider_agnostic": True,
        "cross_act_reuse": True,
    }
    best_for = [
        "act-by-act documentary production with manual clip selection",
        "fast B-roll acquisition when you know what you need",
        "downloading clips from multiple providers in one call",
        "building clip libraries without CLIP embedding overhead",
    ]
    not_good_for = [
        "semantic similarity ranking (use corpus_builder + clip_search)",
        "automated slot filling without human review",
    ]
    fallback_tools = ["corpus_builder", "pexels_video"]

    input_schema = {
        "type": "object",
        "required": ["output_dir", "queries"],
        "properties": {
            "output_dir": {
                "type": "string",
                "description": (
                    "Directory where clips and thumbnails are saved. "
                    "e.g. projects/foo/assets/video/raw_act2"
                ),
            },
            "queries": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search term for stock APIs",
                        },
                        "slot_id": {
                            "type": "string",
                            "description": (
                                "Optional slot reference (e.g. 'slot_03'). "
                                "Used to organize output and track provenance."
                            ),
                        },
                        "kind": {
                            "type": "string",
                            "enum": ["video", "image", "any"],
                            "default": "video",
                        },
                    },
                },
            },
            "sources": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Source adapter names to search (e.g. ['pexels','archive_org']). "
                    "Defaults to all available sources."
                ),
            },
            "clips_per_query": {
                "type": "integer",
                "default": 3,
                "minimum": 1,
                "maximum": 20,
                "description": (
                    "How many clips to download per query (across all sources). "
                    "Lower = faster. 2-3 is enough for manual selection."
                ),
            },
            "max_candidates_total": {
                "type": "integer",
                "default": 24,
                "minimum": 1,
                "maximum": 200,
                "description": (
                    "Hard cap on candidates considered across the invocation, "
                    "including rejected and reused candidates."
                ),
            },
            "max_bytes_per_clip": {
                "type": "integer",
                "default": 100663296,
                "minimum": 1048576,
                "description": (
                    "Hard streamed-byte ceiling per candidate (default 96 MiB)."
                ),
            },
            "max_total_download_bytes": {
                "type": "integer",
                "default": 536870912,
                "minimum": 1048576,
                "description": (
                    "Hard aggregate streamed-byte ceiling (default 512 MiB)."
                ),
            },
            "filters": {
                "type": "object",
                "properties": {
                    "min_duration": {"type": "number"},
                    "max_duration": {"type": "number"},
                    "orientation": {
                        "type": "string",
                        "enum": ["landscape", "portrait", "square"],
                    },
                    "min_width": {"type": "integer"},
                    "max_width": {"type": "integer"},
                },
            },
            "extract_thumbnails": {
                "type": "boolean",
                "default": True,
                "description": (
                    "Extract a mid-frame thumbnail from each video for visual "
                    "inspection. Uses ffmpeg, not CLIP."
                ),
            },
            "skip_existing": {
                "type": "boolean",
                "default": True,
                "description": "Skip download if a file with the same clip_id already exists.",
            },
            "timeout_seconds": {
                "type": "number",
                "default": 600,
                "minimum": 1,
                "description": (
                    "Overall wall-clock deadline for search, download, and thumbnail "
                    "work. Defaults to 10 minutes. On timeout, returns partial progress "
                    "instead of relying on an external process interrupt."
                ),
            },
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=2000, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["timeout", "rate_limit"])
    side_effects = [
        "downloads clips to <output_dir>/clips/",
        "extracts thumbnails to <output_dir>/thumbnails/",
        "calls external stock APIs",
    ]
    user_visible_verification = [
        "Browse <output_dir>/thumbnails/ to visually verify clip matches",
        "Play clips from <output_dir>/clips/ to check quality",
    ]

    def get_status(self) -> ToolStatus:
        try:
            from tools.video.stock_sources import available_sources
        except Exception:
            return ToolStatus.UNAVAILABLE
        if len(available_sources()) == 0:
            return ToolStatus.UNAVAILABLE
        return ToolStatus.AVAILABLE

    def get_info(self) -> dict[str, Any]:
        info = super().get_info()
        try:
            from tools.video.stock_sources import source_catalog, source_summary
            info["source_provider_menu"] = source_catalog()
            info["source_provider_summary"] = source_summary()
        except Exception:
            info["source_provider_menu"] = []
            info["source_provider_summary"] = {
                "configured": 0,
                "total": 0,
                "available_source_names": [],
                "unavailable_source_names": [],
            }
        return info

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0  # all sources are free-tier

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        start = time.time()
        try:
            from tools.video.stock_sources import (
                SearchFilters,
                all_sources,
                available_sources,
                get_source,
                source_summary,
            )

            output_dir = Path(inputs["output_dir"])
            queries: list[dict] = list(inputs["queries"])
            source_names: Optional[list[str]] = inputs.get("sources")
            filters_in: dict = inputs.get("filters") or {}
            clips_per_query = int(inputs.get("clips_per_query", 3))
            extract_thumbs = bool(inputs.get("extract_thumbnails", True))
            skip_existing = bool(inputs.get("skip_existing", True))
            timeout_seconds = float(inputs.get("timeout_seconds", 600))
            max_candidates_total = int(
                inputs.get("max_candidates_total", _DEFAULT_MAX_CANDIDATES_TOTAL)
            )
            max_bytes_per_clip = int(
                inputs.get("max_bytes_per_clip", _DEFAULT_MAX_BYTES_PER_CLIP)
            )
            max_total_download_bytes = int(
                inputs.get(
                    "max_total_download_bytes", _DEFAULT_MAX_TOTAL_DOWNLOAD_BYTES
                )
            )
            if max_candidates_total <= 0:
                raise ValueError("max_candidates_total must be positive")
            download_budget = _DownloadBudget(
                max_bytes_per_clip=max_bytes_per_clip,
                max_total_bytes=max_total_download_bytes,
            )
            deadline = start + timeout_seconds

            clips_dir = output_dir / "clips"
            thumbs_dir = output_dir / "thumbnails"
            clips_dir.mkdir(parents=True, exist_ok=True)
            if extract_thumbs:
                thumbs_dir.mkdir(parents=True, exist_ok=True)

            # --- Resolve sources ---
            if source_names:
                sources = []
                unavailable: list[str] = []
                known = {src.name: src for src in all_sources()}
                for name in source_names:
                    s = known.get(name)
                    if s is None:
                        try:
                            s = get_source(name)
                        except KeyError:
                            return ToolResult(
                                success=False,
                                error=f"Unknown stock source: {name!r}. "
                                      f"Available: {[src.name for src in all_sources()]}",
                            )
                    if s.is_available():
                        sources.append(s)
                    else:
                        unavailable.append(name)
                if unavailable:
                    summary = source_summary()
                    return ToolResult(
                        success=False,
                        error=(
                            f"Requested sources unavailable: {', '.join(unavailable)}. "
                            f"Available: {', '.join(summary['available_source_names']) or 'none'}."
                        ),
                    )
            else:
                sources = available_sources()

            if not sources:
                return ToolResult(
                    success=False,
                    error="No stock sources available. " + self.install_instructions,
                )

            # --- Search and download ---
            downloaded: list[dict] = []
            errors: list[dict] = []
            skipped = 0
            per_source_counts: dict[str, int] = {s.name: 0 for s in sources}
            queries_started = 0
            candidates_considered = 0
            semantic_candidates_reviewed = 0
            technical_rejects = 0
            duplicate_technical_rejects = 0
            seen_technical_rejects: set[tuple[str, str, str, str]] = set()

            def register_technical_reject(
                *, phase: str, source: str, clip_id: str, error: str
            ) -> None:
                nonlocal technical_rejects, duplicate_technical_rejects
                identity = (source, clip_id, phase, error)
                if identity in seen_technical_rejects:
                    duplicate_technical_rejects += 1
                else:
                    seen_technical_rejects.add(identity)
                    technical_rejects += 1
                errors.append({
                    "phase": phase,
                    "clip_id": clip_id,
                    "source": source,
                    "error": error,
                })

            def progress_data() -> dict[str, Any]:
                return {
                    "output_dir": str(output_dir),
                    "clips_downloaded": len(
                        [d for d in downloaded if not d.get("skipped_existing")]
                    ),
                    "clips_reused": skipped,
                    "total_clips": len(downloaded),
                    "per_source_counts": per_source_counts,
                    "queries_run": queries_started,
                    "resolved_sources": [s.name for s in sources],
                    "clips": downloaded,
                    "errors": errors[:25],
                    "candidates_considered": candidates_considered,
                    "semantic_candidates_reviewed": semantic_candidates_reviewed,
                    "technical_rejects": technical_rejects,
                    "duplicate_technical_rejects": duplicate_technical_rejects,
                    "bytes_downloaded": download_budget.total_bytes,
                    "max_candidates_total": max_candidates_total,
                    "max_bytes_per_clip": max_bytes_per_clip,
                    "max_total_download_bytes": max_total_download_bytes,
                }

            def timeout_result(
                *,
                phase: str,
                query: str = "",
                source: str = "",
                clip_id: str = "",
            ) -> ToolResult:
                elapsed = time.time() - start
                return ToolResult(
                    success=False,
                    error=(
                        f"Direct clip search timed out after {timeout_seconds:.1f}s "
                        f"during {phase}."
                    ),
                    data={
                        **progress_data(),
                        "timed_out": True,
                        "phase": phase,
                        "query": query,
                        "source": source,
                        "clip_id": clip_id,
                        "elapsed_seconds": round(elapsed, 2),
                        "timeout_seconds": timeout_seconds,
                    },
                    cost_usd=0.0,
                    duration_seconds=round(elapsed, 2),
                )

            def limit_result(
                error: Exception,
                *,
                phase: str,
                query: str = "",
                source: str = "",
                clip_id: str = "",
            ) -> ToolResult:
                _cleanup_partial_files(clips_dir)
                elapsed = time.time() - start
                return ToolResult(
                    success=False,
                    error=f"Direct clip search stopped at a hard limit: {error}",
                    data={
                        **progress_data(),
                        "budget_exhausted": True,
                        "phase": phase,
                        "query": query,
                        "source": source,
                        "clip_id": clip_id,
                        "elapsed_seconds": round(elapsed, 2),
                    },
                    cost_usd=0.0,
                    duration_seconds=round(elapsed, 2),
                )

            def timed_out() -> bool:
                return time.time() >= deadline

            for q_spec in queries:
                if timed_out():
                    return timeout_result(phase="query", query=q_spec.get("query", ""))

                query = q_spec["query"]
                queries_started += 1
                slot_id = q_spec.get("slot_id", "")
                kind = q_spec.get("kind", "video")
                collected_for_query = 0

                filters = SearchFilters(
                    kind=kind,
                    per_page=max(clips_per_query * 2, 10),  # fetch extra for filtering
                    min_duration=filters_in.get("min_duration"),
                    max_duration=filters_in.get("max_duration"),
                    orientation=filters_in.get("orientation"),
                    min_width=filters_in.get("min_width"),
                    max_width=filters_in.get("max_width"),
                )

                for src in sources:
                    if timed_out():
                        return timeout_result(phase="search", query=query, source=src.name)

                    if collected_for_query >= clips_per_query:
                        break

                    try:
                        with _requests_deadline(deadline):
                            candidates = src.search(query, filters)
                    except _DeadlineExceeded:
                        return timeout_result(phase="search", query=query, source=src.name)
                    except Exception as e:
                        errors.append({
                            "phase": "search",
                            "source": src.name,
                            "query": query,
                            "error": f"{type(e).__name__}: {e}",
                        })
                        continue

                    for cand in candidates:
                        if collected_for_query >= clips_per_query:
                            break
                        if semantic_candidates_reviewed >= max_candidates_total:
                            return limit_result(
                                _DownloadQuotaExceeded(
                                    f"candidate cap {max_candidates_total} reached",
                                    scope="candidates",
                                ),
                                phase="candidate_selection",
                                query=query,
                                source=src.name,
                            )
                        candidates_considered += 1

                        metadata_error = _candidate_filter_error(cand, filters)
                        if metadata_error:
                            register_technical_reject(
                                phase="metadata_filter",
                                clip_id=cand.clip_id,
                                source=src.name,
                                error=metadata_error,
                            )
                            continue

                        if timed_out():
                            return timeout_result(
                                phase="download",
                                query=query,
                                source=src.name,
                                clip_id=cand.clip_id,
                            )

                        clip_id = cand.clip_id
                        ext = _guess_ext(cand)
                        clip_path = clips_dir / f"{clip_id}{ext}"

                        # Reused files still have to satisfy today's filters. A stale
                        # landscape or corrupt clip must not bypass validation merely because
                        # it already exists.
                        if skip_existing and clip_path.exists() and clip_path.stat().st_size > 1024:
                            try:
                                existing_probe = _probe_media(
                                    clip_path,
                                    timeout_seconds=remaining_seconds(deadline),
                                )
                                validation_error = _probed_filter_error(
                                    cand.kind, existing_probe, filters
                                )
                                if validation_error:
                                    raise _MediaValidationError(validation_error)
                            except _DeadlineExceeded:
                                return timeout_result(
                                    phase="validation",
                                    query=query,
                                    source=src.name,
                                    clip_id=clip_id,
                                )
                            except Exception as e:
                                register_technical_reject(
                                    phase="validation",
                                    clip_id=clip_id,
                                    source=src.name,
                                    error=f"{type(e).__name__}: {e}",
                                )
                                _cleanup_file(clip_path)
                                _cleanup_file(thumbs_dir / f"{clip_id}.jpg")
                                continue

                            semantic_candidates_reviewed += 1
                            skipped += 1
                            thumb_path = thumbs_dir / f"{clip_id}.jpg"
                            downloaded.append({
                                "clip_id": clip_id,
                                "source": cand.source,
                                "source_id": cand.source_id,
                                "source_url": cand.source_url,
                                "query": query,
                                "slot_id": slot_id,
                                "kind": cand.kind,
                                "path": str(clip_path),
                                "thumbnail": str(thumb_path) if thumb_path.exists() else "",
                                "duration": existing_probe["duration"],
                                "width": existing_probe["width"],
                                "height": existing_probe["height"],
                                "file_size_bytes": clip_path.stat().st_size,
                                "creator": cand.creator,
                                "license": cand.license,
                                "source_tags": cand.source_tags,
                                "skipped_existing": True,
                            })
                            collected_for_query += 1
                            continue

                        # Download to a hidden partial path. Only validated bytes are
                        # atomically promoted to the final filename.
                        partial_path = clip_path.with_name(
                            f".{clip_path.stem}.part{clip_path.suffix}"
                        )
                        _cleanup_file(partial_path)
                        download_budget.start_clip()
                        try:
                            with _requests_deadline(
                                deadline, download_budget=download_budget
                            ):
                                src.download(cand, partial_path)
                            if not partial_path.exists() or partial_path.stat().st_size < 1024:
                                raise _MediaValidationError(
                                    "Download produced empty or tiny file"
                                )
                            download_budget.reconcile_file_size(
                                partial_path.stat().st_size
                            )
                            probe = _probe_media(
                                partial_path,
                                timeout_seconds=remaining_seconds(deadline),
                            )
                            validation_error = _probed_filter_error(
                                cand.kind, probe, filters
                            )
                            if validation_error:
                                raise _MediaValidationError(validation_error)
                            partial_path.replace(clip_path)
                        except _DeadlineExceeded:
                            _cleanup_file(partial_path)
                            return timeout_result(
                                phase="download",
                                query=query,
                                source=src.name,
                                clip_id=clip_id,
                            )
                        except _DownloadQuotaExceeded as e:
                            _cleanup_file(partial_path)
                            return limit_result(
                                e,
                                phase="download",
                                query=query,
                                source=src.name,
                                clip_id=clip_id,
                            )
                        except _MediaValidationError as e:
                            _cleanup_file(partial_path)
                            register_technical_reject(
                                phase="validation",
                                clip_id=clip_id,
                                source=src.name,
                                error=str(e),
                            )
                            continue
                        except Exception as e:
                            _cleanup_file(partial_path)
                            errors.append({
                                "phase": "download",
                                "clip_id": clip_id,
                                "source": src.name,
                                "error": f"{type(e).__name__}: {e}",
                            })
                            continue

                        if not clip_path.exists() or clip_path.stat().st_size < 1024:
                            errors.append({
                                "phase": "download",
                                "clip_id": clip_id,
                                "source": src.name,
                                "error": "Download produced empty or tiny file",
                            })
                            try:
                                if clip_path.exists():
                                    clip_path.unlink()
                            except OSError:
                                pass
                            continue

                        semantic_candidates_reviewed += 1
                        downloaded_record = {
                            "clip_id": clip_id,
                            "source": cand.source,
                            "source_id": cand.source_id,
                            "source_url": cand.source_url,
                            "query": query,
                            "slot_id": slot_id,
                            "kind": cand.kind,
                            "path": str(clip_path),
                            "thumbnail": "",
                            "duration": probe["duration"],
                            "width": probe["width"],
                            "height": probe["height"],
                            "file_size_bytes": clip_path.stat().st_size,
                            "creator": cand.creator,
                            "license": cand.license,
                            "source_tags": cand.source_tags,
                            "skipped_existing": False,
                        }
                        downloaded.append(downloaded_record)
                        per_source_counts[src.name] = per_source_counts.get(src.name, 0) + 1
                        collected_for_query += 1

                        # Extract thumbnail
                        if extract_thumbs and cand.kind == "video":
                            if timed_out():
                                return timeout_result(
                                    phase="thumbnail",
                                    query=query,
                                    source=src.name,
                                    clip_id=clip_id,
                                )
                            thumb_path = thumbs_dir / f"{clip_id}.jpg"
                            try:
                                _extract_mid_thumbnail(
                                    clip_path,
                                    thumb_path,
                                    timeout_seconds=remaining_seconds(deadline),
                                )
                                if thumb_path.exists():
                                    downloaded_record["thumbnail"] = str(thumb_path)
                            except _DeadlineExceeded:
                                return timeout_result(
                                    phase="thumbnail",
                                    query=query,
                                    source=src.name,
                                    clip_id=clip_id,
                                )
                            except Exception:
                                pass  # thumbnail failure is non-fatal

            elapsed = time.time() - start

            return ToolResult(
                success=True,
                data=progress_data(),
                cost_usd=0.0,
                duration_seconds=round(elapsed, 2),
            )

        except Exception as e:
            import traceback
            return ToolResult(
                success=False,
                error=f"{type(e).__name__}: {e}\n{traceback.format_exc()[-800:]}",
            )


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------



def _cleanup_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _cleanup_partial_files(clips_dir: Path) -> None:
    if not clips_dir.exists():
        return
    for path in clips_dir.glob(".*.part.*"):
        _cleanup_file(path)


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _orientation(width: int, height: int) -> str:
    if width <= 0 or height <= 0:
        return "unknown"
    if abs(width - height) <= max(width, height) * 0.05:
        return "square"
    return "portrait" if height > width else "landscape"


def _candidate_filter_error(cand: Any, filters: Any) -> str:
    """Reject known mismatches before any bytes are requested."""
    kind = str(getattr(cand, "kind", "")).lower()
    if filters.kind != "any" and kind != filters.kind:
        return f"kind {kind!r} does not match requested {filters.kind!r}"
    width = int(getattr(cand, "width", 0) or 0)
    height = int(getattr(cand, "height", 0) or 0)
    duration = _number(getattr(cand, "duration", 0.0))
    if filters.orientation and width > 0 and height > 0:
        actual = _orientation(width, height)
        if actual != filters.orientation:
            return f"declared orientation {actual} does not match {filters.orientation}"
    if filters.min_width is not None and width > 0 and width < filters.min_width:
        return f"declared width {width} is below minimum {filters.min_width}"
    if filters.max_width is not None and width > 0 and width > filters.max_width:
        return f"declared width {width} exceeds maximum {filters.max_width}"
    if kind == "video" and duration > 0:
        if filters.min_duration is not None and duration < filters.min_duration:
            return f"declared duration {duration:.3f}s is below {filters.min_duration}s"
        if filters.max_duration is not None and duration > filters.max_duration:
            return f"declared duration {duration:.3f}s exceeds {filters.max_duration}s"
    return ""


def _probe_media(path: Path, *, timeout_seconds: float) -> dict[str, float | int]:
    remaining = max(0.1, float(timeout_seconds))
    timeout = min(_FFPROBE_VALIDATION_TIMEOUT_SECONDS, remaining)
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,duration:format=duration",
        "-of", "json",
        str(path),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired as exc:
        if remaining <= _FFPROBE_VALIDATION_TIMEOUT_SECONDS:
            raise _DeadlineExceeded("ffprobe exceeded the remaining deadline") from exc
        raise _MediaValidationError(
            "ffprobe exceeded the 15-second media-validation timeout"
        ) from exc
    except FileNotFoundError as exc:
        raise _MediaValidationError("ffprobe is required for downloaded media") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-300:]
        raise _MediaValidationError(f"ffprobe rejected downloaded media: {detail}")
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise _MediaValidationError("ffprobe returned invalid JSON") from exc
    streams = payload.get("streams") or []
    stream = streams[0] if streams else {}
    duration = _number(stream.get("duration")) or _number(
        (payload.get("format") or {}).get("duration")
    )
    return {
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "duration": duration,
    }


def _probed_filter_error(kind: str, probe: dict[str, Any], filters: Any) -> str:
    width = int(probe.get("width") or 0)
    height = int(probe.get("height") or 0)
    duration = _number(probe.get("duration"))
    if width <= 0 or height <= 0:
        return "downloaded media has no measurable video geometry"
    if kind == "video" and duration <= 0:
        return "downloaded video has no measurable positive duration"
    actual_orientation = _orientation(width, height)
    if filters.orientation and actual_orientation != filters.orientation:
        return (
            f"probed orientation {actual_orientation} ({width}x{height}) does not "
            f"match requested {filters.orientation}"
        )
    if filters.min_width is not None and width < filters.min_width:
        return f"probed width {width} is below minimum {filters.min_width}"
    if filters.max_width is not None and width > filters.max_width:
        return f"probed width {width} exceeds maximum {filters.max_width}"
    if kind == "video":
        if filters.min_duration is not None and duration < filters.min_duration:
            return f"probed duration {duration:.3f}s is below {filters.min_duration}s"
        if filters.max_duration is not None and duration > filters.max_duration:
            return f"probed duration {duration:.3f}s exceeds {filters.max_duration}s"
    return ""

def _guess_ext(cand) -> str:
    """Extract a sensible file extension from a candidate's URL."""
    known = {".mp4", ".mov", ".mkv", ".webm", ".ogv", ".m4v",
             ".jpg", ".jpeg", ".png", ".tif", ".tiff"}
    path = urllib.parse.urlparse(cand.download_url).path
    ext = Path(path).suffix.lower()
    if ext in known:
        return ".jpg" if ext == ".jpeg" else ext
    return ".mp4" if cand.kind == "video" else ".jpg"


def remaining_seconds(deadline: float) -> float:
    remaining = deadline - time.time()
    if remaining <= 0:
        raise _DeadlineExceeded("direct_clip_search deadline exceeded")
    return remaining


def _clamp_timeout(timeout: Any, remaining: float) -> Any:
    if timeout is None:
        return remaining
    if isinstance(timeout, tuple):
        return tuple(min(float(part), remaining) for part in timeout)
    try:
        return min(float(timeout), remaining)
    except (TypeError, ValueError):
        return remaining


@contextmanager
def _requests_deadline(
    deadline: float,
    *,
    download_budget: Optional[_DownloadBudget] = None,
):
    """Clamp adapter requests calls to the direct-search deadline.

    Stock-source adapters are intentionally simple and call `requests.get`
    directly. Keeping the deadline wrapper here avoids widening every adapter
    method signature while still preventing streaming downloads from running
    past the tool-level budget.
    """
    import requests

    original_get = requests.get

    def get_with_deadline(*args, **kwargs):
        remaining = remaining_seconds(deadline)
        kwargs["timeout"] = _clamp_timeout(kwargs.get("timeout"), remaining)
        response = original_get(*args, **kwargs)
        if download_budget is not None:
            headers = getattr(response, "headers", {}) or {}
            download_budget.preflight_content_length(
                headers.get("Content-Length") or headers.get("content-length")
            )
        original_iter_content = getattr(response, "iter_content", None)
        if callable(original_iter_content):
            def iter_content_with_deadline(*iter_args, **iter_kwargs):
                for chunk in original_iter_content(*iter_args, **iter_kwargs):
                    remaining_seconds(deadline)
                    if download_budget is not None and chunk:
                        download_budget.consume(len(chunk))
                    yield chunk

            response.iter_content = iter_content_with_deadline
        return response

    requests.get = get_with_deadline
    try:
        yield
    finally:
        requests.get = original_get


def _extract_mid_thumbnail(
    video_path: Path,
    thumb_path: Path,
    *,
    timeout_seconds: float = 15,
) -> None:
    """Extract a single frame from the middle of the video via ffmpeg.

    This is deliberately simple — one frame, no CLIP, no motion score.
    The agent or user inspects the thumbnail visually to decide if the
    clip is a good match.
    """
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + timeout_seconds

    # Probe duration first
    probe_cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        str(video_path),
    ]
    try:
        probe_timeout = min(10, remaining_seconds(deadline))
        result = subprocess.run(
            probe_cmd, capture_output=True, text=True, timeout=probe_timeout
        )
        duration = float(result.stdout.strip() or "0")
    except (ValueError, subprocess.TimeoutExpired, FileNotFoundError):
        duration = 0

    # Seek to the middle (or 2 seconds in if duration unknown)
    seek_time = max(0.5, duration / 2) if duration > 1 else 2.0

    extract_cmd = [
        "ffmpeg", "-y",
        "-ss", str(round(seek_time, 2)),
        "-i", str(video_path),
        "-frames:v", "1",
        "-q:v", "3",
        str(thumb_path),
    ]
    extract_timeout = min(15, remaining_seconds(deadline))
    subprocess.run(
        extract_cmd, capture_output=True, timeout=extract_timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
