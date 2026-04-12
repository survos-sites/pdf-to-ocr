import os
import hashlib
import tempfile
import httpx
import img2pdf
import fitz  # PyMuPDF
import ocrmypdf
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from pathlib import Path
from pydantic import BaseModel, Field

app = FastAPI(title="PDF to OCR Service")

CACHE_DIR = Path(tempfile.mkdtemp())


class MaterializeRequest(BaseModel):
    image_urls: list[str] = Field(..., min_length=1)
    title: str | None = None
    author: str | None = None
    keywords: str | None = None
    language: str | None = None


def _cache_key(url: str) -> str:
    """Consistent cache key from URL."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _download_pdf(url: str) -> Path:
    """Download a PDF and cache locally. Returns path to raw file."""
    key = _cache_key(url)
    raw_path = CACHE_DIR / f"{key}_raw.pdf"
    if raw_path.exists():
        return raw_path
    try:
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
        raw_path.write_bytes(resp.content)
        return raw_path
    except httpx.HTTPError as e:
        raise HTTPException(status_code=400, detail=f"Failed to download PDF: {e}")


def _download_file(url: str, dest_path: Path, kind: str) -> None:
    try:
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
        dest_path.write_bytes(resp.content)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=400, detail=f"Failed to download {kind}: {e}")


def _ensure_ocr(url: str) -> Path:
    """Download + OCR a PDF. Returns path to searchable PDF."""
    key = _cache_key(url)
    ocr_path = CACHE_DIR / f"{key}_ocr.pdf"
    if ocr_path.exists():
        return ocr_path

    raw_path = _download_pdf(url)
    try:
        ocrmypdf.ocr(
            str(raw_path),
            str(ocr_path),
            deskew=True,
            skip_text=True,
            optimize=2,
            language=os.environ.get("OCR_LANGUAGE", "eng"),
        )
    except ocrmypdf.exceptions.PriorOcrFoundError:
        # Already has text layer — just copy it
        ocr_path.write_bytes(raw_path.read_bytes())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OCR failed: {e}")

    return ocr_path


@app.get("/")
def index():
    return {
        "status": "ok",
        "endpoints": {
            "/ocr?url=": "Returns searchable PDF",
            "POST /materialize": "Builds a searchable PDF/A from ordered JPG URLs",
            "/text?url=": "Returns JSON with per-page text",
            "/page-image?url=&page=1&dpi=200": "Returns a page as PNG",
            "/thumbnail?url=&page=1": "Returns a low-res page thumbnail",
        },
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "pdf-to-ocr",
        "cache_dir": str(CACHE_DIR),
    }


@app.get("/ocr")
def ocr_pdf(url: str = Query(..., description="URL of PDF to OCR")):
    """Download a PDF, run OCRmyPDF, return the searchable PDF."""
    ocr_path = _ensure_ocr(url)
    return FileResponse(
        ocr_path,
        media_type="application/pdf",
        filename="ocr-result.pdf",
    )


@app.post("/materialize")
def materialize_pdfa(payload: MaterializeRequest):
    """Build a PDF/A from ordered JPG URLs, then OCR it into a searchable PDF."""
    language = payload.language or os.environ.get("OCR_LANGUAGE", "eng")
    temp_dir = Path(tempfile.mkdtemp())

    try:
        image_paths = []
        for i, image_url in enumerate(payload.image_urls):
            image_path = temp_dir / f"page_{i:04d}.jpg"
            _download_file(image_url, image_path, f"image {i + 1}")
            image_paths.append(image_path)

        raw_pdf_path = temp_dir / "materialized_raw.pdf"
        raw_pdf_path.write_bytes(
            img2pdf.convert([str(image_path) for image_path in image_paths])
        )

        output_pdf_path = temp_dir / "materialized_pdfa.pdf"
        ocr_kwargs = {
            "output_type": "pdfa-2",
            "deskew": True,
            "rotate_pages": True,
            "clean_final": True,
            "optimize": 2,
            "language": language,
        }
        if payload.title:
            ocr_kwargs["title"] = payload.title
        if payload.author:
            ocr_kwargs["author"] = payload.author
        if payload.keywords:
            ocr_kwargs["keywords"] = payload.keywords

        ocrmypdf.ocr(
            str(raw_pdf_path),
            str(output_pdf_path),
            **ocr_kwargs,
        )

        return Response(
            content=output_pdf_path.read_bytes(),
            media_type="application/pdf",
            headers={"Content-Disposition": 'inline; filename="materialized.pdf"'},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Materialization failed: {e}")
    finally:
        for path in temp_dir.glob("*"):
            path.unlink(missing_ok=True)
        temp_dir.rmdir()


@app.get("/text")
def extract_text(url: str = Query(..., description="URL of PDF")):
    """OCR if needed, then return extracted text per page as JSON."""
    ocr_path = _ensure_ocr(url)
    doc = fitz.open(str(ocr_path))
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text().strip()
        pages.append({"page": i + 1, "text": text})
    doc.close()

    return JSONResponse({
        "url": url,
        "page_count": len(pages),
        "pages": pages,
    })


@app.get("/page-image")
def page_image(
    url: str = Query(..., description="URL of PDF"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    dpi: int = Query(200, ge=72, le=600, description="Resolution"),
):
    """Render a single page of the OCR'd PDF as a PNG."""
    ocr_path = _ensure_ocr(url)
    doc = fitz.open(str(ocr_path))
    if page > len(doc):
        doc.close()
        raise HTTPException(
            status_code=404,
            detail=f"Page {page} not found (PDF has {len(doc)} pages)",
        )
    pix = doc[page - 1].get_pixmap(dpi=dpi)
    png_bytes = pix.tobytes("png")
    doc.close()
    return Response(content=png_bytes, media_type="image/png")


@app.get("/thumbnail")
def thumbnail(
    url: str = Query(..., description="URL of PDF"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
):
    """Low-res thumbnail (72 DPI) of a page."""
    ocr_path = _ensure_ocr(url)
    doc = fitz.open(str(ocr_path))
    if page > len(doc):
        doc.close()
        raise HTTPException(
            status_code=404,
            detail=f"Page {page} not found (PDF has {len(doc)} pages)",
        )
    pix = doc[page - 1].get_pixmap(dpi=72)
    png_bytes = pix.tobytes("png")
    doc.close()
    return Response(content=png_bytes, media_type="image/png")
