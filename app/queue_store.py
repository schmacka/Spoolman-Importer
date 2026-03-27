import asyncio
import json
import os
from typing import Optional


class QueueStore:
    def __init__(self, data_dir: str) -> None:
        self._data_dir = data_dir
        self._queue_file = os.path.join(data_dir, "queue.json")
        self._images_dir = os.path.join(data_dir, "queue_images")
        self._lock = asyncio.Lock()
        os.makedirs(self._images_dir, exist_ok=True)

    def image_path(self, item_id: str) -> str:
        return os.path.join(self._images_dir, f"{item_id}.jpg")

    async def _load(self) -> list[dict]:
        if not os.path.exists(self._queue_file):
            return []
        with open(self._queue_file) as f:
            return json.load(f)

    async def _save(self, items: list[dict]) -> None:
        with open(self._queue_file, "w") as f:
            json.dump(items, f, indent=2)

    async def all(self) -> list[dict]:
        async with self._lock:
            return await self._load()

    async def get(self, item_id: str) -> Optional[dict]:
        async with self._lock:
            items = await self._load()
        return next((i for i in items if i["id"] == item_id), None)

    async def add(self, item: dict) -> None:
        async with self._lock:
            items = await self._load()
            items.append(item)
            await self._save(items)

    async def update(self, item_id: str, **fields) -> Optional[dict]:
        async with self._lock:
            items = await self._load()
            for item in items:
                if item["id"] == item_id:
                    item.update(fields)
                    await self._save(items)
                    return item
            return None

    async def remove(self, item_id: str) -> Optional[dict]:
        async with self._lock:
            items = await self._load()
            for i, item in enumerate(items):
                if item["id"] == item_id:
                    items.pop(i)
                    await self._save(items)
                    return item
            return None

    async def cleanup_stuck(self) -> None:
        async with self._lock:
            items = await self._load()
            changed = False
            for item in items:
                if item.get("status") == "analyzing":
                    item["status"] = "failed"
                    item["error"] = "Interrupted — please retry"
                    changed = True
            if changed:
                await self._save(items)
