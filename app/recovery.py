"""Crash-recovery copies of the document being edited.

While the document has unsaved changes, the window asks for a copy every
minute in the recovery folder. A lock file marks the session as alive; at
start-up, copies whose lock is free belong to a session that ended
unexpectedly and are offered to the user. Only QtCore is used (locks, thread).
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QLockFile, QThread

from .model import Document
from .storage import save_project


class RecoveryWriter(QThread):
    """Writes a recovery copy and its metadata; ``run`` may also be called directly."""

    def __init__(self, document: Document, revision: int, project: Path, meta: Path,
                 project_path: str | None, parent=None):
        super().__init__(parent)
        self.document: Document | None = document
        self.revision = revision
        self.project = project
        self.meta = meta
        self.project_path = project_path
        self.succeeded = False
        self.error: str | None = None  # why the copy could not be written

    def run(self):
        if self.document is None:
            return
        try:
            save_project(self.document, self.project)
            self.meta.write_text(json.dumps({
                "project_path": self.project_path,
                "saved_at": time.time(),
            }), encoding="utf-8")
        except (OSError, ValueError) as exc:
            self.error = str(exc)
            return
        self.succeeded = True


class SessionRecovery:
    """Recovery copy of one window, and the copies left behind by crashed sessions."""

    def __init__(self, directory: Path, parent=None):
        self.directory = Path(directory)
        self.parent = parent  # Qt parent of the writer threads
        self.session_id = uuid4().hex
        self.lock: QLockFile | None = None
        self.autosaved_revision: int | None = None
        self.task: RecoveryWriter | None = None
        # Called with the reason when a copy cannot be written (on the interface thread).
        self.on_failure: Callable[[str], None] | None = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            lock = QLockFile(str(self.directory / f"{self.session_id}.lock"))
            if lock.tryLock(0):
                self.lock = lock
        except OSError:
            pass
        self.remove_orphan_locks()

    def files(self, session_id: str) -> tuple[Path, Path]:
        """The copy and its metadata."""
        return self.directory / f"{session_id}.manta", self.directory / f"{session_id}.json"

    def remove_orphan_locks(self) -> None:
        """Delete locks and metadata of dead sessions that left no copy behind (nothing to restore)."""
        if not self.directory.is_dir():
            return
        session_ids = {path.stem for pattern in ("*.lock", "*.json") for path in self.directory.glob(pattern)}
        for session_id in session_ids:
            project, meta = self.files(session_id)
            if session_id == self.session_id or project.exists():
                continue
            lock = QLockFile(str(self.directory / f"{session_id}.lock"))
            if lock.tryLock(0):  # free: its owner is gone
                try:
                    meta.unlink(missing_ok=True)
                except OSError:
                    pass
                lock.unlock()  # unlocking also removes the file

    def write(self, document: Document, revision: int, project_path: Path | None, background: bool) -> bool:
        """Write the copy of this session; True when a copy was written (or started).

        With ``background``, a thread writes it from a snapshot of the document,
        so that compressing and verifying a large project never freezes the interface.
        """
        if self.lock is None or self.autosaved_revision == revision:
            return False  # no lock, or nothing changed since the last copy
        if self.task is not None:
            return False  # the previous copy is still being written
        project, meta = self.files(self.session_id)
        # Layers are copied and image bytes never change: the thread reads a stable snapshot.
        task = RecoveryWriter(document.clone(), revision, project, meta,
                              str(project_path) if project_path else None, self.parent)
        if not background:
            task.run()
            self._finish(task)
            return task.succeeded
        self.task = task
        task.finished.connect(lambda: self._finished(task))
        task.start()
        return True

    def _finished(self, task: RecoveryWriter) -> None:
        if task is not self.task:
            return  # discarded meanwhile: the copy was already deleted
        self.task = None
        self._finish(task)

    def _finish(self, task: RecoveryWriter) -> None:
        if task.succeeded:
            self.autosaved_revision = task.revision
        elif task.error is not None and self.on_failure is not None:
            self.on_failure(task.error)
        self._release(task)

    @staticmethod
    def _release(task: RecoveryWriter) -> None:
        # The snapshot may keep images the document no longer uses alive.
        task.document = None
        task.deleteLater()

    def discard(self, session_id: str) -> None:
        """Delete a copy (this session's after a save, or one the user restored or refused)."""
        if session_id == self.session_id and self.task is not None:
            # Let a running copy finish first, or it would reappear once deleted.
            task, self.task = self.task, None
            task.wait()
            self._release(task)
        for path in self.files(session_id):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        if session_id == self.session_id:
            self.autosaved_revision = None

    def candidates(self) -> list[dict]:
        """Copies left by sessions that are no longer running, newest first; their locks are held."""
        candidates: list[dict] = []
        if not self.directory.is_dir():
            return candidates
        # The copy is listed even without its metadata: a crash between the two
        # writes of a copy must not leave it unreachable on disk.
        for project in self.directory.glob("*.manta"):
            session_id = project.stem
            if session_id == self.session_id or not project.is_file():
                continue
            lock = QLockFile(str(self.directory / f"{session_id}.lock"))
            if not lock.tryLock(0):
                continue  # another Manta Layers window still owns this copy
            try:
                meta = json.loads(self.files(session_id)[1].read_text(encoding="utf-8"))
            except (OSError, ValueError):
                meta = {}
            if not isinstance(meta, dict):
                meta = {}
            if not meta.get("saved_at"):
                try:
                    meta["saved_at"] = project.stat().st_mtime
                except OSError:
                    pass
            candidates.append({"id": session_id, "project": project, "meta": meta, "lock": lock})
        return sorted(candidates, key=lambda item: item["meta"].get("saved_at") or 0, reverse=True)

    def close(self) -> None:
        """Normal end of the session: its copy and its lock go away."""
        self.discard(self.session_id)
        if self.lock is not None:
            self.lock.unlock()
            self.lock = None


def recovery_text(candidate: dict, index: int, count: int) -> tuple[str, str]:
    """Question and details shown for one recovery copy."""
    saved_at = candidate["meta"].get("saved_at")
    when = time.strftime("%d/%m/%Y à %H:%M", time.localtime(saved_at)) if saved_at else "une date inconnue"
    original = candidate["meta"].get("project_path")
    project = f"\nProjet : {Path(original).name}" if original else "\nProjet jamais enregistré"
    position = f" (copie {index + 1} sur {count})" if count > 1 else ""
    others = ("\n\nLes autres copies restent disponibles et seront proposées au prochain démarrage."
              if count - index > 1 else "")
    return (f"Manta Layers s'est fermé de façon imprévue. Une copie de travail du {when} "
            f"a été conservée{position}.{project}",
            "Restaurer cette copie, la supprimer, ou décider au prochain démarrage ?" + others)
