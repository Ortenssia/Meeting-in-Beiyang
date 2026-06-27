"""File-transfer runtime state helpers."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.backend.services.file_transfer_state import (
    FILE_CANCEL,
    FILE_RESUME_REQ,
    FILE_RESUME_RESP,
    FileTransferState,
)


def test_file_transfer_constants_are_protocol_strings():
    assert FILE_CANCEL == "FILE_CANCEL"
    assert FILE_RESUME_REQ == "FILE_RESUME_REQ"
    assert FILE_RESUME_RESP == "FILE_RESUME_RESP"


def test_file_transfer_state_tracks_sender_lifecycle():
    state = FileTransferState()

    state.register_sender("file-1", "demo.bin", "Bob")
    sender = state.mark_sender_cancelled("file-1")

    assert sender["filename"] == "demo.bin"
    assert sender["to_name"] == "Bob"
    assert state.sender_cancelled("file-1") is True
    assert state.pop_sender("file-1")["filename"] == "demo.bin"
    assert state.sender_cancelled("file-1") is False


def test_file_transfer_state_resolves_active_file_id_by_filename():
    state = FileTransferState()
    state.incoming_files["incoming-id"] = {"filename": "received.txt"}
    state.register_sender("sender-id", "sent.txt", "Alice")

    assert state.active_file_id_for("received.txt") == "incoming-id"
    assert state.active_file_id_for("sent.txt") == "sender-id"
    assert state.active_file_id_for("missing.txt") == ""
