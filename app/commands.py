"""Undoable steps of the main window's history.

A DocumentCommand keeps the document before and after a change (see
MainWindow._push for how unchanged layers are shared); a SelectionCommand
keeps the selection masks, PNG-compressed.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from PySide6.QtGui import QUndoCommand

from .model import Document

if TYPE_CHECKING:
    from .window import MainWindow

# Arrow key presses closer than this in time are one undo step.
NUDGE_MERGE_SECONDS = 1.0


class DocumentCommand(QUndoCommand):
    def __init__(self, win: "MainWindow", before: Document, after: Document,
                 description: str, selected_before: str | None, selected_after: str | None,
                 merge_key=None):
        super().__init__(description)
        self.win = win
        self.before = before
        self.after = after
        self.selected_before = selected_before
        self.selected_after = selected_after
        # Commands sharing a merge key and close in time collapse into one step.
        self.merge_key = merge_key
        self.timestamp = time.monotonic()
        # Document and scene built before the command is pushed (see MainWindow._push):
        # the first redo shows them instead of building them again.
        self.prepared: tuple[Document, object] | None = None

    def id(self):
        return 1 if self.merge_key is not None else -1

    def mergeWith(self, other):
        if (not isinstance(other, DocumentCommand) or other.merge_key != self.merge_key
                or other.timestamp - self.timestamp > NUDGE_MERGE_SECONDS):
            return False
        self.after = other.after
        self.selected_after = other.selected_after
        self.timestamp = other.timestamp
        return True

    def _apply(self, document: Document, selected: str | None, undoing: bool):
        prepared, self.prepared = self.prepared, None
        try:
            if prepared is not None:
                self.win.install_document(prepared[0], selected, scene=prepared[1])
            else:
                self.win.install_document(document.clone(), selected)
        except Exception as exc:
            self.win.command_failed(self, exc, undoing)

    def undo(self):
        self._apply(self.before, self.selected_before, True)

    def redo(self):
        self._apply(self.after, self.selected_after, False)


class SelectionCommand(QUndoCommand):
    """Undoable selection change; masks are kept PNG-compressed."""

    def __init__(self, win: "MainWindow", before: bytes | None, after: bytes | None, description: str):
        super().__init__(description)
        self.win = win
        self.before = before
        self.after = after

    def undo(self):
        self.win._install_selection(self.before)

    def redo(self):
        self.win._install_selection(self.after)
