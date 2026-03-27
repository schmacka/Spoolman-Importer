# Multi-Spool Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-spool upload flow with a persistent queue that lets users drop multiple photos at once, track per-item AI analysis, and review/confirm each spool individually.

**Architecture:** Client-orchestrated sequential analysis — JS POSTs files one-at-a-time to `/queue/upload`, which runs analysis synchronously and saves results to `/data/queue.json`. The index page becomes a two-zone UI: upload drop zone on top, queue grid below. Old `/analyze` and `/create` endpoints are removed.

**Tech Stack:** FastAPI, Jinja2, Pico CSS, vanilla JS, `asyncio.Lock` for queue file safety, `pytest` + `pytest-asyncio` + `starlette.testclient.TestClient` for tests.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `requirements-dev.txt` | pytest, pytest-asyncio |
| Create | `pytest.ini` | asyncio_mode = auto |
| Create | `tests/__init__.py` | package marker |
| Create | `tests/conftest.py` | shared fixtures (TestClient, mocks) |
| Create | `app/queue_store.py` | QueueStore: read/write queue.json, image files |
| Create | `tests/test_queue_store.py` | unit tests for QueueStore |
| Create | `tests/test_queue_endpoints.py` | endpoint integration tests |
| Modify | `app/main.py` | add queue endpoints, wire QueueStore in lifespan, remove /analyze + /create |
| Rewrite | `app/templates/index.html` | upload zone + queue grid |
| Modify | `app/templates/review.html` | dynamic form action, error banner, "Back to queue" nav |
| Delete | `app/templates/success.html` | replaced by success banner on index page |

---

## Task 1: Test infrastructure

**Files:**
- Create: `requirements-dev.txt`
- Create: `pytest.ini`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create dev requirements**

```
# requirements-dev.txt
pytest==8.3.5
pytest-asyncio==0.25.3
```

- [ ] **Step 2: Create pytest.ini**

```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 3: Create tests/__init__.py**

```python
```
(empty file)

- [ ] **Step 4: Create tests/conftest.py**

```python
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_PATH", str(tmp_path))
    monkeypatch.setenv("SPOOLMAN_URL", "http://spoolman.test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    with (
        patch("app.main.analyze_image", new_callable=AsyncMock) as mock_analyze,
        patch("app.main.SpoolmanClient") as MockSpoolman,
        patch("app.spoolmandb.SpoolmanDB.refresh", new_callable=AsyncMock),
    ):
        mock_analyze.return_value = {
            "vendor": "TestBrand",
            "material": "PLA",
            "color_name": "Black",
            "color_hex": "000000",
            "weight_g": 1000,
            "diameter_mm": 1.75,
            "temp_min": 190,
            "temp_max": 220,
            "bed_temp": 60,
            "density": 1.24,
        }
        mock_spoolman = MockSpoolman.return_value
        mock_spoolman.find_vendor = AsyncMock(return_value=[])
        mock_spoolman.find_filament = AsyncMock(return_value=[])
        mock_spoolman.create_vendor = AsyncMock(return_value={"id": 1, "name": "TestBrand"})
        mock_spoolman.create_filament = AsyncMock(return_value={"id": 1, "name": "TestBrand PLA Black"})
        mock_spoolman.create_spool = AsyncMock(return_value={"id": 42})

        from app.main import app

        with TestClient(app) as tc:
            import app.main as main_module

            yield tc, main_module.queue_store, mock_analyze, mock_spoolman
```

- [ ] **Step 5: Install dev dependencies**

```bash
pip install -r requirements-dev.txt
```

- [ ] **Step 6: Run pytest to confirm setup works**

```bash
pytest --collect-only
```
Expected: `no tests ran` (0 errors, collection succeeds)

- [ ] **Step 7: Commit**

```bash
git add requirements-dev.txt pytest.ini tests/
git commit -m "chore: add test infrastructure (pytest, pytest-asyncio)"
```

---

## Task 2: QueueStore

**Files:**
- Create: `tests/test_queue_store.py`
- Create: `app/queue_store.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_queue_store.py
import asyncio
import json
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_queue_store.py -v
```
Expected: `ImportError: cannot import name 'QueueStore'`

- [ ] **Step 3: Implement QueueStore**

```python
# app/queue_store.py
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
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_queue_store.py -v
```
Expected: all 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/queue_store.py tests/test_queue_store.py
git commit -m "feat: add QueueStore for persistent spool queue"
```

---

## Task 3: Wire QueueStore into main.py + GET /queue/items

**Files:**
- Modify: `app/main.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_queue_endpoints.py` (create the file):

```python
# tests/test_queue_endpoints.py
import pytest


def test_queue_items_empty(client):
    tc, queue_store, mock_analyze, mock_spoolman = client
    resp = tc.get("/queue/items")
    assert resp.status_code == 200
    assert resp.json() == []


def test_queue_items_returns_items(client):
    tc, queue_store, mock_analyze, mock_spoolman = client
    import asyncio
    asyncio.get_event_loop().run_until_complete(
        queue_store.add({"id": "abc", "status": "ready", "filename": "a.jpg"})
    )
    resp = tc.get("/queue/items")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["id"] == "abc"
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_queue_endpoints.py -v
```
Expected: `404 Not Found` for `/queue/items`

- [ ] **Step 3: Update main.py**

Add these imports at the top of `app/main.py`:

```python
import uuid
from datetime import datetime, timezone
from fastapi.responses import JSONResponse, RedirectResponse
from .queue_store import QueueStore
```

Replace the existing `lifespan` function and add `queue_store` global:

```python
queue_store: QueueStore  # initialized in lifespan


@asynccontextmanager
async def lifespan(app: FastAPI):
    global queue_store
    data_path = os.getenv("DATA_PATH", "/data")
    queue_store = QueueStore(data_path)
    await queue_store.cleanup_stuck()
    await spoolmandb.refresh()
    yield
```

Add the new endpoint after the existing `GET /` route:

```python
@app.get("/queue/items")
async def queue_items():
    return await queue_store.all()
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_queue_endpoints.py::test_queue_items_empty tests/test_queue_endpoints.py::test_queue_items_returns_items -v
```
Expected: both PASS

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_queue_endpoints.py
git commit -m "feat: wire QueueStore into app lifespan, add GET /queue/items"
```

---

## Task 4: POST /queue/upload

**Files:**
- Modify: `app/main.py`
- Modify: `tests/test_queue_endpoints.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_queue_endpoints.py`:

```python
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
    import os
    tc, queue_store, mock_analyze, mock_spoolman = client
    resp = tc.post(
        "/queue/upload",
        files={"file": ("spool.jpg", b"fake-image-data", "image/jpeg")},
    )
    item = resp.json()
    assert os.path.exists(item["image_path"])


def test_upload_persists_to_queue(client):
    import asyncio
    tc, queue_store, mock_analyze, mock_spoolman = client
    resp = tc.post(
        "/queue/upload",
        files={"file": ("spool.jpg", b"fake-image-data", "image/jpeg")},
    )
    item_id = resp.json()["id"]
    stored = asyncio.get_event_loop().run_until_complete(queue_store.get(item_id))
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
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_queue_endpoints.py::test_upload_returns_ready_item -v
```
Expected: `404 Not Found`

- [ ] **Step 3: Implement /queue/upload in main.py**

Add after the `/queue/items` endpoint:

```python
@app.post("/queue/upload")
async def queue_upload(file: UploadFile = File(...)):
    cfg = _cfg()
    image_bytes = await file.read()
    mime_type = file.content_type or "image/jpeg"
    item_id = str(uuid.uuid4())
    image_path = queue_store.image_path(item_id)

    with open(image_path, "wb") as f:
        f.write(image_bytes)

    item: dict = {
        "id": item_id,
        "status": "analyzing",
        "filename": file.filename or "unknown.jpg",
        "image_path": image_path,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data": {},
        "barcode": None,
        "db_match": None,
        "error": None,
    }
    await queue_store.add(item)

    try:
        barcode = scan_barcode(image_bytes)
        data = await analyze_image(
            image_bytes,
            mime_type,
            anthropic_api_key=cfg["anthropic_api_key"],
            openrouter_api_key=cfg["openrouter_api_key"],
            openrouter_model=cfg["openrouter_model"],
        )
        db_match = spoolmandb.search(
            data.get("vendor"),
            data.get("material"),
            data.get("color_name"),
        )
        if db_match:
            for db_key, data_key in [
                ("density", "density"),
                ("diameter", "diameter_mm"),
                ("spool_weight", "spool_weight"),
                ("temp_min", "temp_min"),
                ("temp_max", "temp_max"),
                ("bed_temp", "bed_temp"),
            ]:
                if db_match.get(db_key) is not None and data.get(data_key) is None:
                    data[data_key] = db_match[db_key]
            if db_match.get("color_hex") and not data.get("color_hex"):
                data["color_hex"] = db_match["color_hex"]
            if db_match.get("article_number") and not data.get("article_number"):
                data["article_number"] = db_match["article_number"]
            if db_match.get("weight") and not data.get("weight_g"):
                data["weight_g"] = db_match["weight"]

        item = await queue_store.update(
            item_id,
            status="ready",
            data=data,
            barcode=barcode,
            db_match=db_match,
        )
    except Exception as exc:
        item = await queue_store.update(item_id, status="failed", error=str(exc))

    return JSONResponse(item)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_queue_endpoints.py -k "upload" -v
```
Expected: all 4 upload tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_queue_endpoints.py
git commit -m "feat: add POST /queue/upload — analyze image and persist to queue"
```

---

## Task 5: Rewrite index.html (queue overview + upload zone)

**Files:**
- Rewrite: `app/templates/index.html`
- Modify: `app/main.py` (GET / passes queue items to template)

- [ ] **Step 1: Update GET / in main.py to pass queue items**

Replace the existing `GET /` route:

```python
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    items = await queue_store.all()
    return templates.TemplateResponse(
        "index.html", {"request": request, "items": items}
    )
```

- [ ] **Step 2: Rewrite app/templates/index.html**

```html
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Filament Analyzer</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
  <style>
    body { padding-bottom: 3rem; }
    header { text-align: center; padding: 2.5rem 1rem 1rem; }
    header h1 { margin-bottom: 0.25rem; }
    header p { color: var(--pico-muted-color); margin: 0; }

    .upload-zone {
      border: 2px dashed var(--pico-muted-border-color);
      border-radius: var(--pico-border-radius);
      padding: 2rem;
      text-align: center;
      cursor: pointer;
      transition: border-color 0.2s, background 0.2s;
    }
    .upload-zone:hover,
    .upload-zone.drag-over { border-color: var(--pico-primary); background: rgba(96,165,250,0.04); }
    .upload-zone input[type="file"] { display: none; }
    .upload-icon { font-size: 3rem; line-height: 1; margin-bottom: 0.5rem; }

    .queue-section { margin-top: 2.5rem; }
    .queue-section h2 { margin-bottom: 1rem; }

    .queue-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
      gap: 1rem;
    }

    .spool-card {
      border: 1px solid var(--pico-muted-border-color);
      border-radius: var(--pico-border-radius);
      overflow: hidden;
      background: var(--pico-card-background-color);
      text-decoration: none;
      color: inherit;
      display: block;
      transition: border-color 0.15s;
    }
    a.spool-card:hover { border-color: var(--pico-primary); }

    .spool-card img {
      width: 100%; height: 140px;
      object-fit: cover; display: block;
      background: var(--pico-muted-border-color);
    }
    .spool-card .card-placeholder {
      width: 100%; height: 140px;
      display: flex; align-items: center; justify-content: center;
      background: var(--pico-muted-border-color);
      font-size: 2rem;
    }
    .card-body { padding: 0.6rem 0.75rem; }
    .card-title { font-size: 0.85rem; font-weight: 600; margin-bottom: 0.3rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .card-sub { font-size: 0.78rem; color: var(--pico-muted-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

    .status-badge {
      display: inline-block; font-size: 0.72rem; font-weight: 600;
      padding: 0.15rem 0.5rem; border-radius: 999px; margin-top: 0.4rem;
    }
    .status-analyzing { background: rgba(250,204,21,0.15); color: #fcd34d; border: 1px solid #ca8a04; }
    .status-ready     { background: rgba(96,165,250,0.15); color: #93c5fd; border: 1px solid #3b82f6; }
    .status-done      { background: rgba(34,197,94,0.12); color: #86efac; border: 1px solid #16a34a; }
    .status-failed    { background: rgba(239,68,68,0.12); color: #fca5a5; border: 1px solid #dc2626; }

    .retry-btn {
      font-size: 0.72rem; padding: 0.2rem 0.5rem;
      margin-top: 0.3rem; display: inline-block;
    }
    .error-text { font-size: 0.72rem; color: var(--pico-muted-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

    .success-banner {
      display: none;
      background: rgba(34,197,94,0.12);
      border: 1px solid #16a34a;
      border-radius: var(--pico-border-radius);
      padding: 0.75rem 1rem;
      margin-bottom: 1.5rem;
      color: #86efac;
    }
    .success-banner.visible { display: block; }
  </style>
</head>
<body>
  <main class="container" style="max-width: 860px">
    <header>
      <h1>Filament Analyzer</h1>
      <p>Drop spool photos below — the AI reads the label and adds them to Spoolman</p>
    </header>

    <div class="success-banner" id="success-banner">
      ✅ Spool added to Spoolman successfully.
    </div>

    <div class="upload-zone" id="upload-zone">
      <input type="file" name="file" id="file-input" accept="image/*" multiple>
      <label for="file-input" style="cursor: pointer; display: block">
        <div class="upload-icon">📷</div>
        <p><strong>Click to select</strong> or drag &amp; drop photos</p>
        <small>Select multiple files — each spool is analyzed automatically</small>
      </label>
    </div>

    <div class="queue-section">
      <h2>Queue</h2>
      <div class="queue-grid" id="queue-grid">
        {% for item in items %}
          {% if item.status == 'ready' %}
            <a class="spool-card" href="/queue/{{ item.id }}/review">
          {% else %}
            <div class="spool-card" data-id="{{ item.id }}">
          {% endif %}
            {% if item.status == 'analyzing' %}
              <div class="card-placeholder" aria-busy="true"></div>
            {% else %}
              <img src="/queue/{{ item.id }}/image" alt="{{ item.filename }}" loading="lazy">
            {% endif %}
            <div class="card-body">
              <div class="card-title">
                {{ (item.data.vendor or '') }}
                {{ (' ' + item.data.material) if item.data.material else '' }}
              </div>
              <div class="card-sub">{{ item.data.color_name or item.filename }}</div>
              {% if item.status == 'analyzing' %}
                <span class="status-badge status-analyzing">Analyzing…</span>
              {% elif item.status == 'ready' %}
                <span class="status-badge status-ready">Ready →</span>
              {% elif item.status == 'done' %}
                <span class="status-badge status-done">Done ✓</span>
              {% elif item.status == 'failed' %}
                <span class="status-badge status-failed">Failed ✗</span>
                <div class="error-text">{{ item.error or '' }}</div>
                <button class="retry-btn secondary outline"
                        onclick="retryItem('{{ item.id }}', this)">Retry</button>
              {% endif %}
            </div>
          {% if item.status == 'ready' %}
            </a>
          {% else %}
            </div>
          {% endif %}
        {% endfor %}
      </div>
    </div>
  </main>

  <script>
    // ── Success banner ───────────────────────────────────────────────────────
    const params = new URLSearchParams(location.search);
    if (params.get('created')) {
      document.getElementById('success-banner').classList.add('visible');
      history.replaceState({}, '', '/');
    }

    // ── Upload handling ──────────────────────────────────────────────────────
    const fileInput  = document.getElementById('file-input');
    const uploadZone = document.getElementById('upload-zone');
    const queueGrid  = document.getElementById('queue-grid');

    function makeCard(tempId, filename) {
      const div = document.createElement('div');
      div.className = 'spool-card';
      div.dataset.tempId = tempId;
      div.innerHTML = `
        <div class="card-placeholder" aria-busy="true"></div>
        <div class="card-body">
          <div class="card-title">${filename}</div>
          <div class="card-sub"></div>
          <span class="status-badge status-analyzing">Analyzing…</span>
        </div>`;
      return div;
    }

    function updateCard(card, item) {
      if (item.status === 'ready') {
        const a = document.createElement('a');
        a.className = 'spool-card';
        a.href = `/queue/${item.id}/review`;
        a.innerHTML = `
          <img src="/queue/${item.id}/image" alt="${item.filename}" loading="lazy">
          <div class="card-body">
            <div class="card-title">${(item.data.vendor || '')} ${item.data.material || ''}</div>
            <div class="card-sub">${item.data.color_name || item.filename}</div>
            <span class="status-badge status-ready">Ready →</span>
          </div>`;
        card.replaceWith(a);
      } else {
        card.innerHTML = `
          <img src="/queue/${item.id}/image" alt="${item.filename}" loading="lazy">
          <div class="card-body">
            <div class="card-title">${item.filename}</div>
            <div class="card-sub"></div>
            <span class="status-badge status-failed">Failed ✗</span>
            <div class="error-text">${item.error || ''}</div>
            <button class="retry-btn secondary outline"
                    onclick="retryItem('${item.id}', this)">Retry</button>
          </div>`;
        card.dataset.id = item.id;
      }
    }

    async function uploadFile(file) {
      const tempId = 'tmp-' + Date.now() + '-' + Math.random();
      const card = makeCard(tempId, file.name);
      queueGrid.prepend(card);

      const formData = new FormData();
      formData.append('file', file);

      try {
        const resp = await fetch('/queue/upload', { method: 'POST', body: formData });
        const item = await resp.json();
        updateCard(card, item);
      } catch (e) {
        card.querySelector('.status-analyzing').className = 'status-badge status-failed';
        card.querySelector('.status-badge').textContent = 'Failed ✗';
      }
    }

    async function processFiles(files) {
      for (const file of Array.from(files)) {
        await uploadFile(file);
      }
    }

    fileInput.addEventListener('change', () => processFiles(fileInput.files));

    uploadZone.addEventListener('dragover', e => {
      e.preventDefault();
      uploadZone.classList.add('drag-over');
    });
    uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('drag-over'));
    uploadZone.addEventListener('drop', e => {
      e.preventDefault();
      uploadZone.classList.remove('drag-over');
      processFiles(e.dataTransfer.files);
    });

    // ── Retry ────────────────────────────────────────────────────────────────
    async function retryItem(itemId, btn) {
      const card = btn.closest('.spool-card');
      card.querySelector('.status-badge').className = 'status-badge status-analyzing';
      card.querySelector('.status-badge').textContent = 'Analyzing…';
      btn.remove();

      const resp = await fetch(`/queue/${itemId}/retry`, { method: 'POST' });
      const item = await resp.json();
      updateCard(card, item);
    }
  </script>
</body>
</html>
```

- [ ] **Step 3: Verify index page loads and shows queue**

```bash
pytest tests/test_queue_endpoints.py::test_queue_items_empty -v
```

Also manually confirm with:
```bash
uvicorn app.main:app --reload
```
Visit `http://localhost:8000` — should show empty queue with upload zone.

- [ ] **Step 4: Commit**

```bash
git add app/main.py app/templates/index.html
git commit -m "feat: rewrite index page as queue overview with upload zone"
```

---

## Task 6: GET /queue/{id}/image + GET /queue/{id}/review + update review.html

**Files:**
- Modify: `app/main.py`
- Modify: `app/templates/review.html`
- Modify: `tests/test_queue_endpoints.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_queue_endpoints.py`:

```python
def test_image_endpoint_returns_image(client):
    import asyncio
    tc, queue_store, mock_analyze, mock_spoolman = client

    # Upload a file to get an item in the queue
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
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_queue_endpoints.py -k "image or review_page" -v
```
Expected: 404 for all

- [ ] **Step 3: Add /queue/{id}/image endpoint to main.py**

Add after `/queue/upload`:

```python
@app.get("/queue/{item_id}/image")
async def queue_image(item_id: str):
    from fastapi.responses import FileResponse
    item = await queue_store.get(item_id)
    if not item or not os.path.exists(item["image_path"]):
        from fastapi import HTTPException
        raise HTTPException(status_code=404)
    return FileResponse(item["image_path"], media_type="image/jpeg")
```

- [ ] **Step 4: Add /queue/{id}/review endpoint to main.py**

```python
@app.get("/queue/{item_id}/review", response_class=HTMLResponse)
async def queue_review(request: Request, item_id: str):
    item = await queue_store.get(item_id)
    if not item or item["status"] not in ("ready", "failed"):
        return RedirectResponse("/", status_code=302)

    cfg = _cfg()
    data = item.get("data") or {}
    client = SpoolmanClient(cfg["spoolman_url"], cfg["spoolman_api_key"])
    existing_vendors = await client.find_vendor(data.get("vendor") or "")
    existing_filaments: list[dict] = []
    if existing_vendors:
        existing_filaments = await client.find_filament(
            existing_vendors[0]["id"],
            data.get("material") or "",
            data.get("color_name") or "",
        )

    with open(item["image_path"], "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode()

    return templates.TemplateResponse(
        "review.html",
        {
            "request": request,
            "item_id": item_id,
            "data": data,
            "barcode": item.get("barcode"),
            "db_match": item.get("db_match"),
            "existing_vendors": existing_vendors,
            "existing_filaments": existing_filaments,
            "image_b64": image_b64,
            "image_mime": "image/jpeg",
            "error": None,
        },
    )
```

- [ ] **Step 5: Update review.html**

Change line 83 from:
```html
        <form method="post" action="/create">
```
to:
```html
        <form method="post" action="/queue/{{ item_id }}/create">
```

Change the nav "Start over" link on line 57 from:
```html
      <ul><li><a href="/">← Start over</a></li></ul>
```
to:
```html
      <ul><li><a href="/">← Back to queue</a></li></ul>
```

Change the "Start over" button in the form-actions div (line 248) from:
```html
            <a href="/" role="button" class="secondary outline">Start over</a>
```
to:
```html
            <a href="/" role="button" class="secondary outline">Back to queue</a>
```

Add an error banner just before `<form method="post"...>` (after the `<h2>` and `<p>` block):

```html
        {% if error %}
        <article style="border-color:#dc2626; background:rgba(239,68,68,0.08); margin-bottom:1rem;">
          <p style="margin:0; color:#fca5a5;">⚠️ {{ error }}</p>
        </article>
        {% endif %}
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_queue_endpoints.py -k "image or review_page" -v
```
Expected: all 4 tests PASS

- [ ] **Step 7: Commit**

```bash
git add app/main.py app/templates/review.html tests/test_queue_endpoints.py
git commit -m "feat: add GET /queue/{id}/image and GET /queue/{id}/review endpoints"
```

---

## Task 7: POST /queue/{id}/create

**Files:**
- Modify: `app/main.py`
- Modify: `tests/test_queue_endpoints.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_queue_endpoints.py`:

```python
def test_create_spool_marks_done_and_redirects(client):
    import asyncio
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

    stored = asyncio.get_event_loop().run_until_complete(queue_store.get(item_id))
    assert stored["status"] == "done"


def test_create_spool_keeps_ready_on_spoolman_error(client):
    import asyncio
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

    stored = asyncio.get_event_loop().run_until_complete(queue_store.get(item_id))
    assert stored["status"] == "ready"
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_queue_endpoints.py -k "create_spool" -v
```
Expected: 404

- [ ] **Step 3: Add /queue/{id}/create to main.py**

```python
@app.post("/queue/{item_id}/create", response_class=HTMLResponse)
async def queue_create(
    request: Request,
    item_id: str,
    vendor_id: Optional[str] = Form(default=None),
    vendor_name: Optional[str] = Form(default=None),
    filament_id: Optional[str] = Form(default=None),
    filament_name: Optional[str] = Form(default=None),
    material: Optional[str] = Form(default=None),
    color_hex: Optional[str] = Form(default=None),
    density: Optional[str] = Form(default=None),
    diameter: Optional[str] = Form(default=None),
    weight: Optional[str] = Form(default=None),
    spool_weight: Optional[str] = Form(default=None),
    temp_min: Optional[str] = Form(default=None),
    temp_max: Optional[str] = Form(default=None),
    bed_temp: Optional[str] = Form(default=None),
    article_number: Optional[str] = Form(default=None),
    remaining_weight: Optional[str] = Form(default=None),
    location: Optional[str] = Form(default=None),
    lot_nr: Optional[str] = Form(default=None),
    comment: Optional[str] = Form(default=None),
):
    item = await queue_store.get(item_id)
    if not item:
        return RedirectResponse("/", status_code=302)

    cfg = _cfg()
    spoolman = SpoolmanClient(cfg["spoolman_url"], cfg["spoolman_api_key"])

    async def _render_error(exc: Exception) -> HTMLResponse:
        data = item.get("data") or {}
        existing_vendors = await spoolman.find_vendor(data.get("vendor") or "")
        existing_filaments: list[dict] = []
        if existing_vendors:
            existing_filaments = await spoolman.find_filament(
                existing_vendors[0]["id"],
                data.get("material") or "",
                data.get("color_name") or "",
            )
        with open(item["image_path"], "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode()
        return templates.TemplateResponse(
            "review.html",
            {
                "request": request,
                "item_id": item_id,
                "data": data,
                "barcode": item.get("barcode"),
                "db_match": item.get("db_match"),
                "existing_vendors": existing_vendors,
                "existing_filaments": existing_filaments,
                "image_b64": image_b64,
                "image_mime": "image/jpeg",
                "error": str(exc),
            },
        )

    try:
        vid: Optional[int] = None
        if vendor_id and vendor_id.strip():
            vid = int(vendor_id.strip())
        elif vendor_name and vendor_name.strip():
            vendor = await spoolman.create_vendor(vendor_name.strip())
            vid = vendor["id"]

        fid: Optional[int] = None
        if filament_id and filament_id.strip():
            fid = int(filament_id.strip())
        else:
            filament_payload: dict = {
                "density": float(density) if density and density.strip() else 1.24,
                "diameter": float(diameter) if diameter and diameter.strip() else 1.75,
            }
            if vid is not None:
                filament_payload["vendor_id"] = vid
            if filament_name and filament_name.strip():
                filament_payload["name"] = filament_name.strip()
            if material and material.strip():
                filament_payload["material"] = material.strip()
            if color_hex and color_hex.strip():
                filament_payload["color_hex"] = color_hex.lstrip("#").strip()
            if weight and weight.strip():
                filament_payload["weight"] = float(weight)
            if spool_weight and spool_weight.strip():
                filament_payload["spool_weight"] = float(spool_weight)
            if temp_min and temp_min.strip():
                filament_payload["settings_extruder_temp"] = int(float(temp_min))
            if bed_temp and bed_temp.strip():
                filament_payload["settings_bed_temp"] = int(float(bed_temp))
            if article_number and article_number.strip():
                filament_payload["article_number"] = article_number.strip()
            filament = await spoolman.create_filament(filament_payload)
            fid = filament["id"]

        spool_payload: dict = {"filament_id": fid}
        if remaining_weight and remaining_weight.strip():
            spool_payload["remaining_weight"] = float(remaining_weight)
        if location and location.strip():
            spool_payload["location"] = location.strip()
        if lot_nr and lot_nr.strip():
            spool_payload["lot_nr"] = lot_nr.strip()
        if comment and comment.strip():
            spool_payload["comment"] = comment.strip()

        await spoolman.create_spool(spool_payload)
        await queue_store.update(item_id, status="done")
        return RedirectResponse(f"/?created={item_id}", status_code=303)

    except Exception as exc:
        return await _render_error(exc)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_queue_endpoints.py -k "create_spool" -v
```
Expected: both PASS

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_queue_endpoints.py
git commit -m "feat: add POST /queue/{id}/create — create spool and mark queue item done"
```

---

## Task 8: POST /queue/{id}/retry + DELETE /queue/{id}

**Files:**
- Modify: `app/main.py`
- Modify: `tests/test_queue_endpoints.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_queue_endpoints.py`:

```python
def test_retry_failed_item_returns_ready(client):
    tc, queue_store, mock_analyze, mock_spoolman = client

    # Upload successfully
    tc.post(
        "/queue/upload",
        files={"file": ("spool.jpg", b"fake-image-data", "image/jpeg")},
    )
    items = tc.get("/queue/items").json()
    item_id = items[0]["id"]

    # Force to failed state
    import asyncio
    asyncio.get_event_loop().run_until_complete(
        queue_store.update(item_id, status="failed", error="old error")
    )

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
    import asyncio
    tc, queue_store, mock_analyze, mock_spoolman = client
    tc.post(
        "/queue/upload",
        files={"file": ("spool.jpg", b"fake-image-data", "image/jpeg")},
    )
    items = tc.get("/queue/items").json()
    item_id = items[0]["id"]

    resp = tc.delete(f"/queue/{item_id}")
    assert resp.status_code == 200

    stored = asyncio.get_event_loop().run_until_complete(queue_store.get(item_id))
    assert stored is None


def test_delete_nonexistent_returns_404(client):
    tc, queue_store, mock_analyze, mock_spoolman = client
    resp = tc.delete("/queue/nonexistent")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_queue_endpoints.py -k "retry or delete" -v
```
Expected: all 4 fail with 404 or 405

- [ ] **Step 3: Add retry and delete endpoints to main.py**

```python
@app.post("/queue/{item_id}/retry")
async def queue_retry(item_id: str):
    from fastapi import HTTPException
    item = await queue_store.get(item_id)
    if not item:
        raise HTTPException(status_code=404)

    cfg = _cfg()
    with open(item["image_path"], "rb") as f:
        image_bytes = f.read()

    await queue_store.update(item_id, status="analyzing", error=None, data={})

    try:
        barcode = scan_barcode(image_bytes)
        data = await analyze_image(
            image_bytes,
            "image/jpeg",
            anthropic_api_key=cfg["anthropic_api_key"],
            openrouter_api_key=cfg["openrouter_api_key"],
            openrouter_model=cfg["openrouter_model"],
        )
        db_match = spoolmandb.search(
            data.get("vendor"),
            data.get("material"),
            data.get("color_name"),
        )
        if db_match:
            for db_key, data_key in [
                ("density", "density"),
                ("diameter", "diameter_mm"),
                ("spool_weight", "spool_weight"),
                ("temp_min", "temp_min"),
                ("temp_max", "temp_max"),
                ("bed_temp", "bed_temp"),
            ]:
                if db_match.get(db_key) is not None and data.get(data_key) is None:
                    data[data_key] = db_match[db_key]
            if db_match.get("color_hex") and not data.get("color_hex"):
                data["color_hex"] = db_match["color_hex"]
            if db_match.get("article_number") and not data.get("article_number"):
                data["article_number"] = db_match["article_number"]
            if db_match.get("weight") and not data.get("weight_g"):
                data["weight_g"] = db_match["weight"]

        item = await queue_store.update(
            item_id, status="ready", data=data, barcode=barcode, db_match=db_match
        )
    except Exception as exc:
        item = await queue_store.update(item_id, status="failed", error=str(exc))

    return JSONResponse(item)


@app.delete("/queue/{item_id}")
async def queue_delete(item_id: str):
    from fastapi import HTTPException
    item = await queue_store.remove(item_id)
    if not item:
        raise HTTPException(status_code=404)
    if os.path.exists(item.get("image_path", "")):
        os.remove(item["image_path"])
    return {"ok": True}
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_queue_endpoints.py -k "retry or delete" -v
```
Expected: all 4 PASS

- [ ] **Step 5: Run full test suite**

```bash
pytest -v
```
Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add app/main.py tests/test_queue_endpoints.py
git commit -m "feat: add POST /queue/{id}/retry and DELETE /queue/{id}"
```

---

## Task 9: Remove old /analyze, /create endpoints and success.html

**Files:**
- Modify: `app/main.py`
- Delete: `app/templates/success.html`

- [ ] **Step 1: Remove /analyze and /create from main.py**

Delete the entire `async def analyze(...)` function (the `@app.post("/analyze", ...)` route).

Delete the entire `async def create_spool(...)` function (the `@app.post("/create", ...)` route).

- [ ] **Step 2: Delete success.html**

```bash
git rm app/templates/success.html
```

- [ ] **Step 3: Run full test suite**

```bash
pytest -v
```
Expected: all tests PASS, no references to removed endpoints

- [ ] **Step 4: Confirm /analyze and /create return 404**

```bash
uvicorn app.main:app --reload
```

```bash
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/analyze
# Expected: 404 or 405
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/create
# Expected: 404 or 405
```

- [ ] **Step 5: Commit**

```bash
git add app/main.py
git commit -m "feat: remove legacy /analyze and /create endpoints, delete success.html"
```

---

## Self-Review Notes

- **SpoolmanDB enrichment duplication:** The enrichment block is duplicated between `/queue/upload` and `/queue/{id}/retry`. This is acceptable (YAGNI — no other caller), but if a third caller appears, extract to a helper.
- **`asyncio.get_event_loop()` in tests:** Some tests use `asyncio.get_event_loop().run_until_complete(...)` to call async queue_store methods. This works but is slightly fragile. If the test runner's event loop policy changes, use `anyio.from_thread.run_sync` instead. For now it's fine.
- **Image MIME type on retry:** Retry hardcodes `"image/jpeg"`. Original MIME type is not stored in the queue item. Files uploaded as PNG/WEBP will be re-analyzed as if JPEG. This is acceptable for a home tool — Claude handles mismatched MIME gracefully.
