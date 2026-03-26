from io import BytesIO

from PIL import Image

try:
    from pyzbar.pyzbar import decode as pyzbar_decode

    PYZBAR_AVAILABLE = True
except ImportError:
    PYZBAR_AVAILABLE = False


def scan_barcode(image_bytes: bytes) -> str | None:
    """Return the first decoded barcode/QR string found in the image, or None."""
    if not PYZBAR_AVAILABLE:
        return None
    try:
        image = Image.open(BytesIO(image_bytes))
        results = pyzbar_decode(image)
        if results:
            return results[0].data.decode("utf-8", errors="replace")
    except Exception as exc:
        print(f"Barcode scan error: {exc}")
    return None
