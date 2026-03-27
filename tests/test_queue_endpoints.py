import asyncio
import os

import pytest


def test_queue_items_empty(client):
    tc, queue_store, mock_analyze, mock_spoolman = client
    resp = tc.get("/queue/items")
    assert resp.status_code == 200
    assert resp.json() == []


def test_queue_items_returns_items(client):
    tc, queue_store, mock_analyze, mock_spoolman = client
    asyncio.run(
        queue_store.add({"id": "abc", "status": "ready", "filename": "a.jpg"})
    )
    resp = tc.get("/queue/items")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["id"] == "abc"


def test_upload_returns_ready_item(client):
    tc, queue_store, mock_analyze, mock_spoolman = client
    resp = tc.post(
        "/queue/upload",
        files={"file": ("spool.jpg", b"fake-image-data", "image/jpeg")},
    )
    assert resp.status_code == 200
    item = resp.json()
    assert item["status"] == "ready"
    assert item["filename"] == "spool.jpg"
    assert item["data"]["vendor"] == "TestBrand"
    assert "id" in item


def test_upload_saves_image_to_disk(client):
    tc, queue_store, mock_analyze, mock_spoolman = client
    resp = tc.post(
        "/queue/upload",
        files={"file": ("spool.jpg", b"fake-image-data", "image/jpeg")},
    )
    item = resp.json()
    assert os.path.exists(item["image_path"])


def test_upload_persists_to_queue(client):
    tc, queue_store, mock_analyze, mock_spoolman = client
    resp = tc.post(
        "/queue/upload",
        files={"file": ("spool.jpg", b"fake-image-data", "image/jpeg")},
    )
    item_id = resp.json()["id"]
    stored = asyncio.run(queue_store.get(item_id))
    assert stored is not None
    assert stored["status"] == "ready"


def test_upload_marks_failed_on_analysis_error(client):
    tc, queue_store, mock_analyze, mock_spoolman = client
    mock_analyze.side_effect = RuntimeError("AI unavailable")
    resp = tc.post(
        "/queue/upload",
        files={"file": ("spool.jpg", b"fake-image-data", "image/jpeg")},
    )
    assert resp.status_code == 200
    item = resp.json()
    assert item["status"] == "failed"
    assert "AI unavailable" in item["error"]
