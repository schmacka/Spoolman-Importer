import os
import pytest
from app.queue_store import QueueStore


@pytest.fixture
def store(tmp_path):
    return QueueStore(str(tmp_path))


async def test_add_and_get(store):
    item = {"id": "abc", "status": "ready", "filename": "a.jpg"}
    await store.add(item)
    result = await store.get("abc")
    assert result == item


async def test_all_returns_list(store):
    assert await store.all() == []
    await store.add({"id": "x", "status": "ready", "filename": "x.jpg"})
    assert len(await store.all()) == 1


async def test_update(store):
    await store.add({"id": "abc", "status": "analyzing", "filename": "a.jpg"})
    updated = await store.update("abc", status="ready", data={"vendor": "Foo"})
    assert updated["status"] == "ready"
    assert updated["data"] == {"vendor": "Foo"}
    # Persisted to disk
    result = await store.get("abc")
    assert result["status"] == "ready"


async def test_update_missing_id_returns_none(store):
    result = await store.update("nonexistent", status="done")
    assert result is None


async def test_remove(store):
    await store.add({"id": "abc", "status": "done", "filename": "a.jpg"})
    removed = await store.remove("abc")
    assert removed["id"] == "abc"
    assert await store.get("abc") is None


async def test_remove_missing_id_returns_none(store):
    result = await store.remove("nonexistent")
    assert result is None


async def test_persists_to_disk(tmp_path):
    store1 = QueueStore(str(tmp_path))
    await store1.add({"id": "abc", "status": "ready", "filename": "a.jpg"})

    store2 = QueueStore(str(tmp_path))
    result = await store2.get("abc")
    assert result is not None
    assert result["id"] == "abc"


async def test_cleanup_stuck_resets_analyzing_to_failed(store):
    await store.add({"id": "stuck", "status": "analyzing", "filename": "a.jpg", "error": None})
    await store.add({"id": "ok", "status": "ready", "filename": "b.jpg", "error": None})
    await store.cleanup_stuck()
    assert (await store.get("stuck"))["status"] == "failed"
    assert (await store.get("stuck"))["error"] == "Interrupted — please retry"
    assert (await store.get("ok"))["status"] == "ready"


def test_image_path(store, tmp_path):
    path = store.image_path("abc")
    assert path == os.path.join(str(tmp_path), "queue_images", "abc.jpg")
