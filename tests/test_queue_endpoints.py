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


def test_image_endpoint_returns_image(client):
    tc, queue_store, mock_analyze, mock_spoolman = client
    tc.post(
        "/queue/upload",
        files={"file": ("spool.jpg", b"fake-image-data", "image/jpeg")},
    )
    items = tc.get("/queue/items").json()
    item_id = items[0]["id"]

    resp = tc.get(f"/queue/{item_id}/image")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/")


def test_image_endpoint_404_for_unknown(client):
    tc, queue_store, mock_analyze, mock_spoolman = client
    resp = tc.get("/queue/nonexistent/image")
    assert resp.status_code == 404


def test_review_page_loads_for_ready_item(client):
    tc, queue_store, mock_analyze, mock_spoolman = client
    tc.post(
        "/queue/upload",
        files={"file": ("spool.jpg", b"fake-image-data", "image/jpeg")},
    )
    items = tc.get("/queue/items").json()
    item_id = items[0]["id"]

    resp = tc.get(f"/queue/{item_id}/review")
    assert resp.status_code == 200
    assert b"Review" in resp.content
    assert b"TestBrand" in resp.content


def test_review_page_redirects_for_unknown_item(client):
    tc, queue_store, mock_analyze, mock_spoolman = client
    resp = tc.get("/queue/nonexistent/review", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/"


def test_create_spool_marks_done_and_redirects(client):
    tc, queue_store, mock_analyze, mock_spoolman = client
    tc.post(
        "/queue/upload",
        files={"file": ("spool.jpg", b"fake-image-data", "image/jpeg")},
    )
    items = tc.get("/queue/items").json()
    item_id = items[0]["id"]

    resp = tc.post(
        f"/queue/{item_id}/create",
        data={"vendor_name": "TestBrand", "material": "PLA"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/?created={item_id}"

    stored = asyncio.run(queue_store.get(item_id))
    assert stored["status"] == "done"


def test_create_spool_keeps_ready_on_spoolman_error(client):
    tc, queue_store, mock_analyze, mock_spoolman = client
    mock_spoolman.create_spool.side_effect = RuntimeError("Spoolman down")

    tc.post(
        "/queue/upload",
        files={"file": ("spool.jpg", b"fake-image-data", "image/jpeg")},
    )
    items = tc.get("/queue/items").json()
    item_id = items[0]["id"]

    resp = tc.post(
        f"/queue/{item_id}/create",
        data={"vendor_name": "TestBrand", "material": "PLA"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert b"Spoolman down" in resp.content

    stored = asyncio.run(queue_store.get(item_id))
    assert stored["status"] == "ready"


def test_retry_failed_item_returns_ready(client):
    tc, queue_store, mock_analyze, mock_spoolman = client
    tc.post(
        "/queue/upload",
        files={"file": ("spool.jpg", b"fake-image-data", "image/jpeg")},
    )
    items = tc.get("/queue/items").json()
    item_id = items[0]["id"]

    asyncio.run(queue_store.update(item_id, status="failed", error="old error"))

    resp = tc.post(f"/queue/{item_id}/retry")
    assert resp.status_code == 200
    item = resp.json()
    assert item["status"] == "ready"
    assert item["error"] is None


def test_retry_nonexistent_returns_404(client):
    tc, queue_store, mock_analyze, mock_spoolman = client
    resp = tc.post("/queue/nonexistent/retry")
    assert resp.status_code == 404


def test_delete_removes_item(client):
    tc, queue_store, mock_analyze, mock_spoolman = client
    tc.post(
        "/queue/upload",
        files={"file": ("spool.jpg", b"fake-image-data", "image/jpeg")},
    )
    items = tc.get("/queue/items").json()
    item_id = items[0]["id"]

    resp = tc.delete(f"/queue/{item_id}")
    assert resp.status_code == 200

    stored = asyncio.run(queue_store.get(item_id))
    assert stored is None


def test_delete_nonexistent_returns_404(client):
    tc, queue_store, mock_analyze, mock_spoolman = client
    resp = tc.delete("/queue/nonexistent")
    assert resp.status_code == 404
