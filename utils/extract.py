
import io
import os

import pdfplumber
import pytesseract
from PIL import Image, ImageOps, ImageFilter

ALLOWED_PDF_EXT = {".pdf"}
ALLOWED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"}


class ExtractionError(Exception):
    """Raised when text cannot be extracted from a document."""


def get_file_ext(filename: str) -> str:
    return os.path.splitext(filename)[1].lower()


def is_supported_file(filename: str) -> bool:
    ext = get_file_ext(filename)
    return ext in ALLOWED_PDF_EXT or ext in ALLOWED_IMAGE_EXT


def _preprocess_image_for_ocr(img: Image.Image) -> Image.Image:
    """Light preprocessing to improve OCR accuracy on scanned documents."""
    gray = ImageOps.grayscale(img)
    gray = gray.filter(ImageFilter.SHARPEN)
    # Simple binarization threshold
    bw = gray.point(lambda x: 0 if x < 140 else 255, mode="1")
    return bw


def extract_text_from_image_bytes(file_bytes: bytes) -> str:
    try:
        img = Image.open(io.BytesIO(file_bytes))
        img.load()
    except Exception as exc:
        raise ExtractionError(f"Could not open image: {exc}") from exc

    try:
        processed = _preprocess_image_for_ocr(img)
        text = pytesseract.image_to_string(processed)
        if not text.strip():
            # Retry on the raw (unprocessed) image as a fallback
            text = pytesseract.image_to_string(img)
        return text.strip()
    except pytesseract.TesseractNotFoundError as exc:
        raise ExtractionError(
            "OCR engine (Tesseract) is not installed on the server."
        ) from exc
    except Exception as exc:
        raise ExtractionError(f"OCR extraction failed: {exc}") from exc


def _detect_column_split(page) -> float | None:
    """
    Detect a vertical gutter for two-column layouts (common in academic
    papers/reports) by histogramming word x-positions and looking for a
    low-density band in the middle third of the page. Returns the x
    coordinate of the gutter, or None if the page looks single-column.
    """
    words = page.extract_words()
    if len(words) < 30:
        return None

    x0_page, _, x1_page, _ = page.bbox
    width = x1_page - x0_page
    if width <= 0:
        return None
    bins = 40
    bin_width = width / bins
    counts = [0] * bins
    for w in words:
        rel_x = w["x0"] - x0_page
        idx = min(bins - 1, max(0, int(rel_x / width * bins)))
        counts[idx] += 1

    mid_lo, mid_hi = int(bins * 0.35), int(bins * 0.65)
    mid_slice = counts[mid_lo:mid_hi]
    if not mid_slice:
        return None

    min_count = min(mid_slice)
    min_idx = mid_lo + mid_slice.index(min_count)
    max_count = max(counts) or 1

    if min_count > 0.2 * max_count:
        return None  # no clear gutter -> single column

    split_x = x0_page + (min_idx + 0.5) * bin_width

    # Confirm the split actually separates most words cleanly.
    left = sum(1 for w in words if w["x1"] <= split_x + 8)
    right = sum(1 for w in words if w["x0"] >= split_x - 8)
    if (left + right) / len(words) < 0.85:
        return None

    return split_x


def _extract_page_text(page) -> str:
    """Extract text from a page, splitting two-column layouts correctly."""
    split_x = _detect_column_split(page)
    if split_x is None:
        return page.extract_text() or ""

    # Use the page's actual bounding box (some PDFs have a non-zero-origin
    # or slightly offset mediabox) rather than assuming (0, 0, width, height).
    x0, top, x1, bottom = page.bbox
    try:
        left_box = page.crop((x0, top, split_x, bottom))
        right_box = page.crop((split_x, top, x1, bottom))
        left_text = left_box.extract_text() or ""
        right_text = right_box.extract_text() or ""
        return (left_text + "\n\n" + right_text).strip()
    except Exception:
        # If cropping fails for any reason (unusual mediabox, rotated page,
        # etc.), fall back to normal single-pass extraction rather than
        # failing the whole document.
        return page.extract_text() or ""


def extract_text_from_pdf_bytes(file_bytes: bytes) -> str:
    """
    Extract text from a PDF, page by page, preserving paragraph breaks.
    Automatically detects and correctly orders two-column layouts.
    Falls back to OCR per-page if a page has no extractable text
    (common for scanned PDFs saved as images).
    """
    pages_text = []
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            if len(pdf.pages) == 0:
                raise ExtractionError("The PDF has no pages.")

            for page in pdf.pages:
                try:
                    page_text = _extract_page_text(page)
                except Exception:
                    page_text = ""
                if not page_text.strip():
                    page_text = _ocr_pdf_page(file_bytes, page.page_number)
                pages_text.append(page_text.strip())
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(f"Could not parse PDF: {exc}") from exc

    full_text = "\n\n".join(p for p in pages_text if p)
    if not full_text.strip():
        raise ExtractionError(
            "No text could be extracted from this PDF, even with OCR."
        )
    return full_text


def _ocr_pdf_page(file_bytes: bytes, page_number: int) -> str:
    """Rasterize a single PDF page and run OCR on it (for scanned pages)."""
    try:
        from pdf2image import convert_from_bytes

        images = convert_from_bytes(
            file_bytes, first_page=page_number, last_page=page_number, dpi=200
        )
        if not images:
            return ""
        processed = _preprocess_image_for_ocr(images[0])
        return pytesseract.image_to_string(processed)
    except Exception:
        # If OCR fallback fails, just return empty text for this page
        # rather than failing the whole document.
        return ""


def extract_text(filename: str, file_bytes: bytes) -> dict:
    """
    Dispatch extraction based on file extension.
    Returns dict: {"text": str, "method": "pdf" | "ocr", "pages": int|None}
    """
    ext = get_file_ext(filename)

    if not file_bytes:
        raise ExtractionError("Uploaded file is empty.")

    if ext in ALLOWED_PDF_EXT:
        text = extract_text_from_pdf_bytes(file_bytes)
        return {"text": text, "method": "pdf"}

    if ext in ALLOWED_IMAGE_EXT:
        text = extract_text_from_image_bytes(file_bytes)
        if not text.strip():
            raise ExtractionError(
                "No readable text was found in this image."
            )
        return {"text": text, "method": "ocr"}

    raise ExtractionError(
        f"Unsupported file type '{ext}'. Please upload a PDF or an image "
        f"(PNG, JPG, BMP, TIFF)."
    )
