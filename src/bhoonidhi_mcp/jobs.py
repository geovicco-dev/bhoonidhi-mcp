"""In-process registry for background download jobs.

A stdio MCP server is request/response — a tool call cannot stream progress
while it runs. So ``download_query`` starts a download on a daemon thread,
records it here keyed by a generated ``job_id``, and returns at once; the agent
polls ``download_status`` (or blocks on ``download_wait``) to report progress
and completion.

The download itself is independent of the conversation: it runs on that daemon
thread regardless of whether anyone is polling. The lifetime limit is deliberate
and honest — a job lives only as long as the server process. If the MCP client
restarts, in-flight jobs are lost, which is why the download tool steers a large
fetch to a standalone command the user owns instead.

The SDK's download runs its own thread pool and fires ``on_progress`` with
``(scene_id, bytes_so_far, total_bytes)`` per chunk — ``bytes_so_far`` is
cumulative for that scene, ``total_bytes`` is the response Content-Length (or
None when the portal doesn't send one). The job aggregates those into overall
bytes, a rate, and per-scene detail so a poll is genuinely informative rather
than just "N scenes started".
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

_lock = threading.Lock()
_jobs: dict[str, DownloadJob] = {}


@dataclass
class _SceneProgress:
    downloaded: int = 0
    total: int | None = None


@dataclass
class DownloadJob:
    """The live state of one background download, updated as it runs."""

    job_id: str
    slug: str
    out_dir: str
    total_scenes: int
    status: str = "started"  # started -> running -> completed | failed
    current_scene: str | None = None
    error: str | None = None
    started_at: float = field(default_factory=time.monotonic)
    ended_at: float | None = None
    _scenes: dict[str, _SceneProgress] = field(default_factory=dict)
    outcomes: list[dict[str, Any]] = field(default_factory=list)
    _done: threading.Event = field(default_factory=threading.Event)

    def note_progress(self, scene_id: str, downloaded: int, total: int | None) -> None:
        with _lock:
            self.status = "running"
            self.current_scene = scene_id
            scene = self._scenes.get(scene_id)
            if scene is None:
                scene = _SceneProgress()
                self._scenes[scene_id] = scene
            scene.downloaded = downloaded
            if total is not None:
                scene.total = total

    def _elapsed(self) -> float:
        end = self.ended_at if self.ended_at is not None else time.monotonic()
        return max(end - self.started_at, 1e-6)

    def snapshot(self) -> dict[str, Any]:
        """A JSON-safe copy of the current state for a poll."""
        with _lock:
            bytes_downloaded = sum(s.downloaded for s in self._scenes.values())
            totals = [s.total for s in self._scenes.values()]
            all_known = bool(totals) and all(t is not None for t in totals)
            bytes_expected = sum(t for t in totals if t is not None) or None
            elapsed = self._elapsed()

            snap: dict[str, Any] = {
                "job_id": self.job_id,
                "slug": self.slug,
                "out_dir": self.out_dir,
                "status": self.status,
                "total_scenes": self.total_scenes,
                "scenes_started": len(self._scenes),
                "current_scene": self.current_scene,
                "bytes_downloaded": bytes_downloaded,
                "mb_downloaded": round(bytes_downloaded / 1_000_000, 1),
                "elapsed_s": round(elapsed, 1),
                "rate_mb_s": round(bytes_downloaded / 1_000_000 / elapsed, 2),
                # Total size is unknown until the portal sends Content-Length for
                # every scene; report it (and a percent) only when fully known.
                "bytes_expected": bytes_expected if all_known else None,
                "percent": (
                    round(100 * bytes_downloaded / bytes_expected, 1)
                    if all_known and bytes_expected
                    else None
                ),
                "per_scene": [
                    {
                        "id": sid,
                        "mb_downloaded": round(s.downloaded / 1_000_000, 1),
                        "mb_total": round(s.total / 1_000_000, 1) if s.total else None,
                    }
                    for sid, s in self._scenes.items()
                ],
            }
            snap["summary"] = _summarize(snap)
            if self.status == "completed":
                snap["outcomes"] = list(self.outcomes)
            if self.status == "failed":
                snap["error"] = self.error
            return snap

    def wait(self, timeout_s: float) -> dict[str, Any]:
        """Block until the job reaches a terminal state or ``timeout_s`` elapses."""
        self._done.wait(timeout=timeout_s)
        return self.snapshot()


def _summarize(snap: dict[str, Any]) -> str:
    """One-line, plain-language read of a job snapshot."""
    if snap["status"] == "completed":
        return f"Done: {snap['mb_downloaded']} MB across {snap['scenes_started']} scene(s)."
    if snap["status"] == "failed":
        return f"Failed after {snap['mb_downloaded']} MB: {snap.get('error', 'unknown error')}."
    if snap["status"] == "started":
        return "Starting — no bytes yet."
    pct = f" ({snap['percent']}%)" if snap["percent"] is not None else ""
    return (
        f"Downloading: {snap['mb_downloaded']} MB{pct} at "
        f"{snap['rate_mb_s']} MB/s, {snap['scenes_started']} of "
        f"{snap['total_scenes']} scene(s) active."
    )


def register(slug: str, out_dir: str, total_scenes: int) -> DownloadJob:
    """Create and store a new job, returning it in the ``started`` state."""
    job = DownloadJob(
        job_id=uuid.uuid4().hex[:12],
        slug=slug,
        out_dir=out_dir,
        total_scenes=total_scenes,
    )
    with _lock:
        _jobs[job.job_id] = job
    return job


def get(job_id: str) -> DownloadJob | None:
    with _lock:
        return _jobs.get(job_id)


def run(
    job: DownloadJob,
    work: Callable[[Callable[[str, int, int | None], None]], list[Any]],
) -> None:
    """Run ``work`` on a daemon thread, feeding it a progress callback.

    ``work`` receives the ``on_progress`` callback to hand the SDK and must
    return the SDK's list of download outcomes. Any exception is captured onto
    the job as a clean ``failed`` state — it never escapes to crash the server.
    The job's completion event is always set, so a waiter is never stranded.
    """

    def _target() -> None:
        def on_progress(scene_id: str, downloaded: int, total: int | None) -> None:
            job.note_progress(scene_id, downloaded, total)

        try:
            outcomes = work(on_progress)
            with _lock:
                job.outcomes = [_shape_outcome(o) for o in outcomes]
                job.status = "completed"
                job.current_scene = None
                job.ended_at = time.monotonic()
        except Exception as exc:  # noqa: BLE001 — surfaced to the agent, not swallowed
            with _lock:
                job.status = "failed"
                job.error = str(exc)
                job.current_scene = None
                job.ended_at = time.monotonic()
        finally:
            job._done.set()

    thread = threading.Thread(target=_target, name=f"download-{job.job_id}", daemon=True)
    thread.start()


# Plain-English gloss for each SDK download outcome status.
_OUTCOME_PHRASE = {
    "downloaded": "downloaded",
    "already_downloaded": "already present — skipped",
    "archived": "archived (open data) — attempted, may 404 until requested on the portal",
    "skipped_on_order": "on-order — skipped, must be requested on the portal first",
    "skipped_priced": "priced — skipped, must be purchased on the portal",
    "failed": "failed",
}


def _shape_outcome(outcome: Any) -> dict[str, Any]:
    """One SDK ``DownloadOutcome`` as agent-facing JSON."""
    shaped: dict[str, Any] = {
        "id": outcome.scene_id,
        "status": outcome.status,
        "meaning": _OUTCOME_PHRASE.get(outcome.status, outcome.status),
    }
    if outcome.path:
        shaped["path"] = outcome.path
    if outcome.bytes_downloaded:
        shaped["mb_downloaded"] = round(outcome.bytes_downloaded / 1_000_000, 1)
    if outcome.error:
        shaped["error"] = outcome.error
    return shaped


def _reset() -> None:
    """Clear the registry — for tests only."""
    with _lock:
        _jobs.clear()
