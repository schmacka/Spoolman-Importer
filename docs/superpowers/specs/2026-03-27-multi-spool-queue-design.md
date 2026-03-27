# Multi-Spool Queue — Design Spec

**Date:** 2026-03-27
**Status:** Approved for implementation

## Overview

Replace the current one-at-a-time upload flow with a persistent queue that lets users drop multiple spool photos at once, track analysis progress, and review/confirm each spool individually before adding to Spoolman.

## Approach

Client-orchestrated sequential analysis. JS drops images and POSTs each to the server one at a time. The server runs analysis synchronously within the request (no background tasks). The queue is persisted to disk. No polling needed — JS drives all state updates directly from fetch responses.

## Data Model

Queue persisted to `/data/queue.json` as a JSON array. Images saved as files under `/data/queue_images/<id>.jpg`.

Each queue item:

```json
{
  "id": "uuid4",
  "status": "analyzing | ready | done | failed",
  "filename": "original_filename.jpg",
  "image_path": "/data/queue_images/<id>.jpg",
  "created_at": "2026-03-27T12:00:00Z",
  "data": { ...AI-extracted fields... },
  "barcode": "...",
  "db_match": { ... },
  "error": null
}
```

A new `QueueStore` class in `app/queue_store.py` handles all reads/writes protected by an `asyncio.Lock` (sufficient for single-process uvicorn).

**Startup behavior:** Any items in `analyzing` state when the server starts (interrupted mid-request) are reset to `failed` with error `"Interrupted — please retry"`.

## API Endpoints

The existing `/analyze` and `/create` endpoints are replaced.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/` | Queue overview page (upload zone + item grid) |
| `POST` | `/queue/upload` | Accept one image, run analysis, save to queue, return JSON `{id, status, data, error}` |
| `GET` | `/queue/items` | Return all queue items as JSON (used by server-side template; available for JS refresh if needed) |
| `GET` | `/queue/{id}/review` | Review page for a single ready item |
| `POST` | `/queue/{id}/create` | Create spool in Spoolman, mark item `done`, redirect to `/?created={id}` |
| `POST` | `/queue/{id}/retry` | Re-run analysis on a failed item using the saved image file |
| `DELETE` | `/queue/{id}` | Remove item from queue and delete its image file |

## UI Flow

### Index page (`/`) — two zones

**Upload zone (top):** Same drag & drop as today but `<input multiple>`. JS iterates dropped files and POSTs each to `/queue/upload` sequentially (awaits each before starting the next). A card appears immediately in the grid with "Analyzing…" status and updates when the response returns.

**Queue grid (below):** One card per spool showing:
- Thumbnail
- Vendor + material + color (or "Unknown")
- Status badge:
  - `Analyzing…` — spinner, not clickable
  - `Ready` — clickable → `/queue/{id}/review`
  - `Done ✓` — grayed out
  - `Failed ✗` — error snippet + Retry button

A `?created={id}` query param on page load triggers an inline success banner identifying the spool just added.

### Review page (`/queue/{id}/review`)

Identical to the current `review.html` form, pre-populated from the queue item's `data`. On submit, POSTs to `/queue/{id}/create`. On success, redirects to `/?created={id}`. On Spoolman API error, re-renders the review page with an inline error (item stays `ready`).

`success.html` is removed — the queue overview with success banner replaces it.

## Error Handling

| Scenario | Behavior |
|----------|---------|
| Analysis fails (AI error, unreadable image) | Item saved as `failed` with error message. `/queue/upload` still returns HTTP 200 with the failed item so the JS card renders. |
| Spool creation fails (Spoolman API error) | Item stays `ready`. Review page re-rendered with inline error message. |
| Retry | `POST /queue/{id}/retry` re-reads the saved image file and re-runs the full analysis pipeline. No re-upload needed. |
| Server killed mid-analysis | On next startup, `analyzing` items are reset to `failed`. |
| Item removal | `DELETE /queue/{id}` deletes image file + removes item from `queue.json`. `Done` items keep their image file intact until explicitly removed. |

## New Files

- `app/queue_store.py` — `QueueStore` class: load/save `queue.json`, file locking, startup cleanup of stuck items
- `app/templates/index.html` — rewritten with upload zone + queue grid
- `app/templates/review.html` — updated form action to `/queue/{id}/create`

## Modified Files

- `app/main.py` — replace `/analyze` + `/create` with queue endpoints; add `QueueStore` to lifespan
- `app/templates/success.html` — removed (replaced by queue overview + banner)

## Out of Scope

- Parallel analysis (sequential is sufficient for home use)
- WebSocket / SSE push (polling not needed given client-driven model)
- Bulk "clear done" action (can be added later)
- Pagination of queue grid (acceptable to scroll for now)
