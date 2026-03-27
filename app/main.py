import base64
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .analyzer import analyze_image
from .barcode import scan_barcode
from .spoolman import SpoolmanClient
from .spoolmandb import SpoolmanDB
from .queue_store import QueueStore

load_dotenv()

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")

spoolmandb = SpoolmanDB()
queue_store: QueueStore  # initialized in lifespan


@asynccontextmanager
async def lifespan(app: FastAPI):
    global queue_store
    data_path = os.getenv("DATA_PATH", "/data")
    queue_store = QueueStore(data_path)
    await queue_store.cleanup_stuck()
    await spoolmandb.refresh()
    yield


app = FastAPI(title="Filament Analyzer", lifespan=lifespan)
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _cfg() -> dict:
    return {
        "spoolman_url": os.getenv("SPOOLMAN_URL", "http://localhost:7912"),
        "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY", ""),
        "openrouter_api_key": os.getenv("OPENROUTER_API_KEY", ""),
        "openrouter_model": os.getenv("OPENROUTER_MODEL", "anthropic/claude-haiku-4-5"),
        "spoolman_api_key": os.getenv("SPOOLMAN_API_KEY", ""),
    }


# ── Routes ────────────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    items = await queue_store.all()
    return templates.TemplateResponse(
        "index.html", {"request": request, "items": items}
    )


@app.get("/queue/items")
async def queue_items():
    return await queue_store.all()


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
        "mime_type": mime_type,
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


@app.get("/queue/{item_id}/image")
async def queue_image(item_id: str):
    item = await queue_store.get(item_id)
    if not item or not os.path.exists(item["image_path"]):
        raise HTTPException(status_code=404)
    return FileResponse(item["image_path"], media_type="image/jpeg")


@app.get("/queue/{item_id}/review", response_class=HTMLResponse)
async def queue_review(request: Request, item_id: str):
    item = await queue_store.get(item_id)
    if not item or item["status"] not in ("ready", "failed"):
        return RedirectResponse("/", status_code=302)

    cfg = _cfg()
    data = item.get("data") or {}
    spoolman_client = SpoolmanClient(cfg["spoolman_url"], cfg["spoolman_api_key"])
    existing_vendors = await spoolman_client.find_vendor(data.get("vendor") or "")
    existing_filaments: list[dict] = []
    if existing_vendors:
        existing_filaments = await spoolman_client.find_filament(
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
        try:
            existing_vendors = await spoolman.find_vendor(data.get("vendor") or "")
            existing_filaments: list[dict] = []
            if existing_vendors:
                existing_filaments = await spoolman.find_filament(
                    existing_vendors[0]["id"],
                    data.get("material") or "",
                    data.get("color_name") or "",
                )
        except Exception:
            existing_vendors = []
            existing_filaments = []
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


@app.post("/queue/{item_id}/retry")
async def queue_retry(item_id: str):
    item = await queue_store.get(item_id)
    if not item:
        raise HTTPException(status_code=404)

    cfg = _cfg()
    await queue_store.update(item_id, status="analyzing", error=None, data={})

    try:
        with open(item["image_path"], "rb") as f:
            image_bytes = f.read()
        barcode = scan_barcode(image_bytes)
        data = await analyze_image(
            image_bytes,
            item.get("mime_type") or "image/jpeg",
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
    item = await queue_store.remove(item_id)
    if not item:
        raise HTTPException(status_code=404)
    if os.path.exists(item.get("image_path", "")):
        os.remove(item["image_path"])
    return {"ok": True}
