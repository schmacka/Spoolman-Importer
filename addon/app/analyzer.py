import base64
import json
import re

import anthropic
import httpx

SYSTEM_PROMPT = """You are a 3D printer filament analyzer. Given a photo of a filament spool,
extract metadata from the label and return it as a single JSON object with these exact keys:

- vendor: brand/manufacturer name (string or null)
- material: filament material type — PLA, PETG, ABS, TPU, ASA, HIPS, PLA+, etc. (string or null)
- color_name: color name as printed on the label (string or null)
- color_hex: best estimate of the filament color as a 6-char hex string WITHOUT # (e.g. "FF0000", null if unclear)
- weight_g: net filament weight in grams as an integer (null if not visible)
- diameter_mm: filament diameter — typically 1.75 or 2.85 (number or null)
- temp_min: minimum recommended print/extruder temperature in Celsius as integer (null if not visible)
- temp_max: maximum recommended print/extruder temperature in Celsius as integer (null if not visible)
- bed_temp: recommended bed temperature in Celsius as integer (null if not visible)
- density: filament density in g/cm³ as a float (null if not visible)

Return ONLY valid JSON. No markdown fences, no extra text."""


def _parse_json(text: str) -> dict:
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if json_match:
        return json.loads(json_match.group())
    return _empty_result()


async def _analyze_anthropic(image_bytes: bytes, api_key: str, mime_type: str) -> dict:
    client = anthropic.AsyncAnthropic(api_key=api_key)
    image_b64 = base64.standard_b64encode(image_bytes).decode()
    message = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": image_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": "Analyze this filament spool and return the JSON.",
                    },
                ],
            }
        ],
    )
    return _parse_json(message.content[0].text.strip())


async def _analyze_openrouter(
    image_bytes: bytes, api_key: str, model: str, mime_type: str
) -> dict:
    image_b64 = base64.standard_b64encode(image_bytes).decode()
    data_url = f"data:{mime_type};base64,{image_b64}"
    payload = {
        "model": model,
        "max_tokens": 512,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {
                        "type": "text",
                        "text": "Analyze this filament spool and return the JSON.",
                    },
                ],
            },
        ],
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=30.0,
        )
        resp.raise_for_status()
    return _parse_json(resp.json()["choices"][0]["message"]["content"].strip())


async def analyze_image(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
    *,
    anthropic_api_key: str = "",
    openrouter_api_key: str = "",
    openrouter_model: str = "anthropic/claude-haiku-4-5",
) -> dict:
    # Normalize MIME type — browsers may send image/jpg
    if mime_type == "image/jpg":
        mime_type = "image/jpeg"

    try:
        if openrouter_api_key:
            return await _analyze_openrouter(
                image_bytes, openrouter_api_key, openrouter_model, mime_type
            )
        if anthropic_api_key:
            return await _analyze_anthropic(image_bytes, anthropic_api_key, mime_type)
    except Exception as exc:
        print(f"AI analysis error: {exc}")

    return _empty_result()


def _empty_result() -> dict:
    return {
        "vendor": None,
        "material": None,
        "color_name": None,
        "color_hex": None,
        "weight_g": None,
        "diameter_mm": None,
        "temp_min": None,
        "temp_max": None,
        "bed_temp": None,
        "density": None,
    }
