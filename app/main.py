import base64
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
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


@app.post("/analyze", response_class=HTMLResponse)
async def analyze(request: Request, file: UploadFile = File(...)):
    cfg = _cfg()
    image_bytes = await file.read()
    mime_type = file.content_type or "image/jpeg"

    # 1. Barcode fast-path
    barcode = scan_barcode(image_bytes)

    # 2. AI vision analysis (OpenRouter if key set, else Anthropic)
    data = await analyze_image(
        image_bytes,
        mime_type,
        anthropic_api_key=cfg["anthropic_api_key"],
        openrouter_api_key=cfg["openrouter_api_key"],
        openrouter_model=cfg["openrouter_model"],
    )

    # 3. SpoolmanDB enrichment — fill in technical fields for known filaments
    db_match = spoolmandb.search(
        data.get("vendor"),
        data.get("material"),
        data.get("color_name"),
    )
    if db_match:
        # DB values fill gaps; user-visible fields (vendor, material, color_name) keep AI values
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

    # 4. Deduplication: find existing Spoolman records
    client = SpoolmanClient(cfg["spoolman_url"], cfg["spoolman_api_key"])
    existing_vendors = await client.find_vendor(data.get("vendor") or "")
    existing_filaments: list[dict] = []
    if existing_vendors:
        existing_filaments = await client.find_filament(
            existing_vendors[0]["id"],
            data.get("material") or "",
            data.get("color_name") or "",
        )

    image_b64 = base64.b64encode(image_bytes).decode()

    return templates.TemplateResponse(
        "review.html",
        {
            "request": request,
            "data": data,
            "barcode": barcode,
            "db_match": db_match,
            "existing_vendors": existing_vendors,
            "existing_filaments": existing_filaments,
            "image_b64": image_b64,
            "image_mime": mime_type,
        },
    )


@app.post("/create", response_class=HTMLResponse)
async def create_spool(
    request: Request,
    # Vendor
    vendor_id: Optional[str] = Form(default=None),
    vendor_name: Optional[str] = Form(default=None),
    # Filament
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
    # Spool
    remaining_weight: Optional[str] = Form(default=None),
    location: Optional[str] = Form(default=None),
    lot_nr: Optional[str] = Form(default=None),
    comment: Optional[str] = Form(default=None),
):
    cfg = _cfg()
    client = SpoolmanClient(cfg["spoolman_url"], cfg["spoolman_api_key"])

    try:
        # Resolve vendor
        vid: Optional[int] = None
        if vendor_id and vendor_id.strip():
            vid = int(vendor_id.strip())
        elif vendor_name and vendor_name.strip():
            vendor = await client.create_vendor(vendor_name.strip())
            vid = vendor["id"]

        # Resolve filament
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

            filament = await client.create_filament(filament_payload)
            fid = filament["id"]

        # Create spool
        spool_payload: dict = {"filament_id": fid}
        if remaining_weight and remaining_weight.strip():
            spool_payload["remaining_weight"] = float(remaining_weight)
        if location and location.strip():
            spool_payload["location"] = location.strip()
        if lot_nr and lot_nr.strip():
            spool_payload["lot_nr"] = lot_nr.strip()
        if comment and comment.strip():
            spool_payload["comment"] = comment.strip()

        spool = await client.create_spool(spool_payload)

        return templates.TemplateResponse(
            "success.html",
            {
                "request": request,
                "spool": spool,
                "spoolman_url": cfg["spoolman_url"],
                "error": None,
            },
        )

    except Exception as exc:
        return templates.TemplateResponse(
            "success.html",
            {
                "request": request,
                "spool": None,
                "spoolman_url": cfg["spoolman_url"],
                "error": str(exc),
            },
        )
