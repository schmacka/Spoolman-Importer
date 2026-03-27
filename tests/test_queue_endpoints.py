import pytest


def test_queue_items_empty(client):
    tc, queue_store, mock_analyze, mock_spoolman = client
    resp = tc.get("/queue/items")
    assert resp.status_code == 200
    assert resp.json() == []


def test_queue_items_returns_items(client):
    import asyncio
    tc, queue_store, mock_analyze, mock_spoolman = client
    asyncio.get_event_loop().run_until_complete(
        queue_store.add({"id": "abc", "status": "ready", "filename": "a.jpg"})
    )
    resp = tc.get("/queue/items")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["id"] == "abc"
