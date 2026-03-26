import base64
import json
import re

import anthropic

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


async def analyze_image(
    image_bytes: bytes,
    api_key: str,
    mime_type: str = "image/jpeg",
) -> dict:
    if not api_key:
        return _empty_result()

    # Normalize MIME type — browsers may send image/jpg
    if mime_type == "image/jpg":
        mime_type = "image/jpeg"

    client = anthropic.AsyncAnthropic(api_key=api_key)
    image_b64 = base64.standard_b64encode(image_bytes).decode()

    try:
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
        text = message.content[0].text.strip()
        # Strip any accidental markdown fences
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        return _empty_result()
    except Exception as exc:
        print(f"Claude analysis error: {exc}")
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
