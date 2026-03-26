import json
import os
import time
from pathlib import Path

import httpx

SPOOLMANDB_URL = "https://donkie.github.io/SpoolmanDB/filaments.json"
CACHE_PATH = Path(os.getenv("DATA_PATH", "/tmp")) / "spoolmandb_cache.json"
CACHE_TTL = 24 * 3600  # 24 hours


class SpoolmanDB:
    def __init__(self) -> None:
        self._filaments: list[dict] = []

    async def refresh(self) -> None:
        """Load from cache if fresh, otherwise fetch from SpoolmanDB."""
        if self._is_cache_valid():
            self._load_from_cache()
            return
        await self._fetch_remote()

    async def _fetch_remote(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(SPOOLMANDB_URL)
                resp.raise_for_status()
                data = resp.json()
                self._filaments = data if isinstance(data, list) else data.get("filaments", [])
                self._write_cache(data)
                print(f"SpoolmanDB: loaded {len(self._filaments)} filaments")
        except Exception as exc:
            print(f"SpoolmanDB fetch failed: {exc}")
            # Fall back to stale cache if available
            if CACHE_PATH.exists():
                self._load_from_cache()

    def _is_cache_valid(self) -> bool:
        if not CACHE_PATH.exists():
            return False
        return (time.time() - CACHE_PATH.stat().st_mtime) < CACHE_TTL

    def _load_from_cache(self) -> None:
        try:
            data = json.loads(CACHE_PATH.read_text())
            self._filaments = data if isinstance(data, list) else data.get("filaments", [])
            print(f"SpoolmanDB: loaded {len(self._filaments)} filaments from cache")
        except Exception as exc:
            print(f"SpoolmanDB cache load error: {exc}")
            self._filaments = []

    def _write_cache(self, data: object) -> None:
        try:
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            CACHE_PATH.write_text(json.dumps(data))
        except Exception as exc:
            print(f"SpoolmanDB cache write error: {exc}")

    # ── Search ────────────────────────────────────────────────────────────────

    def search(
        self,
        vendor_name: str | None,
        material: str | None,
        color_name: str | None,
    ) -> dict | None:
        """Fuzzy-search for the best matching filament. Returns normalized dict or None."""
        if not self._filaments:
            return None

        v = _norm(vendor_name)
        m = _norm(material)
        c = _norm(color_name)

        best: dict | None = None
        best_score = 0

        for f in self._filaments:
            score = 0
            fv = _norm(self._vendor_name(f))
            fm = _norm(f.get("material"))
            fn = _norm(f.get("name"))

            if v and (v in fv or fv in v):
                score += 3
            if m and (m in fm or fm in m):
                score += 2
            if c and (c in fn or fn in c):
                score += 2

            if score > best_score:
                best_score = score
                best = f

        # Require at least vendor + one other field matching
        if best_score >= 4:
            return self._normalize(best)
        return None

    def _vendor_name(self, f: dict) -> str:
        vendor = f.get("vendor", {})
        if isinstance(vendor, dict):
            return vendor.get("name", "")
        return str(vendor)

    def _normalize(self, f: dict) -> dict:
        settings = f.get("settings", {})
        return {
            "id": f.get("id"),
            "name": f.get("name"),
            "vendor_name": self._vendor_name(f),
            "material": f.get("material"),
            "density": f.get("density"),
            "diameter": f.get("diameter"),
            "weight": f.get("weight"),
            "spool_weight": f.get("spool_weight"),
            "color_hex": f.get("color_hex"),
            "article_number": f.get("article_number"),
            "temp_min": settings.get("nozzle_temp_min"),
            "temp_max": settings.get("nozzle_temp_max"),
            "bed_temp": settings.get("bed_temp_min"),
        }


def _norm(s: str | None) -> str:
    if not s:
        return ""
    return s.lower().replace(" ", "").replace("-", "").replace("_", "")
