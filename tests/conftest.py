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
