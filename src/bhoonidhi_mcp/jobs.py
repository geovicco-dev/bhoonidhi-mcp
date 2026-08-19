"""In-process registry for background download jobs.

A stdio MCP server is request/response — a tool call cannot stream progress
while it runs. So ``download_query`` starts a download on a daemon thread,
records it here keyed by a generated ``job_id``, and returns at once; the agent
polls ``download_status`` to report progress and completion.

The lifetime limit is deliberate and honest: a job lives only as long as the
server process. If the MCP client restarts, in-flight jobs are lost — which is
why the download tool steers genuinely large fetches to a standalone ``bhd``
command the user owns instead.

The SDK's download runs its own thread pool internally; the single daemon thread
here just waits on that call and updates the job record under a lock.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

_lock = threading.Lock()
_jobs: dict[str, DownloadJob] = {}


@dataclass
class DownloadJob:
    """The live state of one background download, updated as it runs.

    ``on_progress`` from the SDK fires ``(scene_id, bytes_so_far, total_bytes)``
    as data arrives; the runner counts distinct scene ids to report "scene N of
    M" without needing per-byte totals the portal doesn't reveal up front.
    """

    job_id: str
    slug: str
    out_dir: str
    total_scenes: int
    status: str = "started"  # started -> running -> completed | failed
    current_scene: str | None = None
    scenes_started: int = 0
    outcomes: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    _seen: set[str] = field(default_factory=set)

    def note_progress(self, scene_id: str) -> None:
        with _lock:
            self.status = "running"
            self.current_scene = scene_id
            if scene_id not in self._seen:
                self._seen.add(scene_id)
                self.scenes_started = len(self._seen)

    def snapshot(self) -> dict[str, Any]:
        """A JSON-safe copy of the current state for a poll."""
        with _lock:
            snap = {
                "job_id": self.job_id,
                "slug": self.slug,
                "out_dir": self.out_dir,
                "status": self.status,
                "total_scenes": self.total_scenes,
                "scenes_started": self.scenes_started,
                "current_scene": self.current_scene,
            }
            if self.status == "completed":
                snap["outcomes"] = list(self.outcomes)
            if self.status == "failed":
                snap["error"] = self.error
            return snap


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


def run(job: DownloadJob, work: Callable[[Callable[[str, int, int | None], None]],
                                         list[Any]]) -> None:
    """Run ``work`` on a daemon thread, feeding it a progress callback.

    ``work`` receives the ``on_progress`` callback to hand the SDK and must
    return the SDK's list of download outcomes. Any exception is captured onto
    the job as a clean ``failed`` state — it never escapes to crash the server.
    """

    def _target() -> None:
        def on_progress(scene_id: str, done: int, total: int | None) -> None:
            job.note_progress(scene_id)

        try:
            outcomes = work(on_progress)
            with _lock:
                job.outcomes = [_shape_outcome(o) for o in outcomes]
                job.status = "completed"
                job.current_scene = None
        except Exception as exc:  # noqa: BLE001 — surfaced to the agent, not swallowed
            with _lock:
                job.status = "failed"
                job.error = str(exc)
                job.current_scene = None

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
        shaped["bytes_downloaded"] = outcome.bytes_downloaded
    if outcome.error:
        shaped["error"] = outcome.error
    return shaped


def _reset() -> None:
    """Clear the registry — for tests only."""
    with _lock:
        _jobs.clear()
