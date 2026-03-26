from typing import Any

import httpx


class SpoolmanClient:
    def __init__(self, base_url: str, api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.headers: dict[str, str] = {}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    # ── Vendor ────────────────────────────────────────────────────────────────

    async def find_vendor(self, name: str) -> list[dict]:
        if not name:
            return []
        async with httpx.AsyncClient(headers=self.headers, timeout=10) as client:
            try:
                resp = await client.get(f"{self.base_url}/api/v1/vendor")
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("items", data) if isinstance(data, dict) else data
                    name_lower = name.lower()
                    return [v for v in items if name_lower in v.get("name", "").lower()]
            except Exception as exc:
                print(f"Spoolman vendor lookup error: {exc}")
        return []

    async def create_vendor(self, name: str) -> dict:
        async with httpx.AsyncClient(headers=self.headers, timeout=10) as client:
            resp = await client.post(
                f"{self.base_url}/api/v1/vendor", json={"name": name}
            )
            resp.raise_for_status()
            return resp.json()

    # ── Filament ──────────────────────────────────────────────────────────────

    async def find_filament(
        self, vendor_id: int, material: str, color_name: str
    ) -> list[dict]:
        params: dict[str, Any] = {"vendor_id": vendor_id}
        async with httpx.AsyncClient(headers=self.headers, timeout=10) as client:
            try:
                resp = await client.get(
                    f"{self.base_url}/api/v1/filament", params=params
                )
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("items", data) if isinstance(data, dict) else data
                    # Narrow down by material and/or color name if provided
                    if material:
                        items = [
                            f
                            for f in items
                            if material.lower()
                            in (f.get("material") or "").lower()
                        ]
                    if color_name:
                        items = [
                            f
                            for f in items
                            if color_name.lower() in (f.get("name") or "").lower()
                        ]
                    return items
            except Exception as exc:
                print(f"Spoolman filament lookup error: {exc}")
        return []

    async def create_filament(self, payload: dict) -> dict:
        async with httpx.AsyncClient(headers=self.headers, timeout=10) as client:
            resp = await client.post(
                f"{self.base_url}/api/v1/filament", json=payload
            )
            resp.raise_for_status()
            return resp.json()

    # ── Spool ─────────────────────────────────────────────────────────────────

    async def create_spool(self, payload: dict) -> dict:
        async with httpx.AsyncClient(headers=self.headers, timeout=10) as client:
            resp = await client.post(
                f"{self.base_url}/api/v1/spool", json=payload
            )
            resp.raise_for_status()
            return resp.json()
