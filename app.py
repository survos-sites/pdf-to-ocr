import os
import tempfile
import httpx
import fitz  # PyMuPDF
import ocrmypdf
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

app = FastAPI(title="PDF to OCR Service")

TEMP_DIR = tempfile.mkdtemp()


@app.get("/")
def index():
    return {"status": "ok", "usage": "GET /?url=https://example.com/scan.pdf"}


@app.get("/ocr")
def ocr_pdf(url: str = Query(..., description="URL of PDF to OCR")):
    """Download a PDF, run OCRmyPDF, return the searchable PDF."""
    try:
        # Download the PDF
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()

        input_path = os.path.join(TEMP_DIR, "input.pdf")
        output_path = os.path.join(TEMP_DIR, "output.pdf")

        with open(input_path, "wb") as f:
            f.write(resp.content)

        # Run OCRmyPDF
        ocrmypdf.ocr(
            input_path,
            output_path,
            deskew=True,
            skip_text=True,
            optimize=2,
            language="eng",
        )

        return FileResponse(
            output_path,
            media_type="application/pdf",
            filename="ocr-result.pdf",
        )

    except httpx.HTTPError as e:
        raise HTTPException(status_code=400, detail=f"Failed to download PDF: {e}")
    except ocrmypdf.exceptions.PriorOcrFoundError:
        # PDF already has OCR text, return it as-is
        return FileResponse(input_path, media_type="application/pdf")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/text")
def extract_text(url: str = Query(..., description="URL of PDF to extract text from")):
    """Download a PDF, run OCR if needed, return extracted text per page."""
    try:
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()

        input_path = os.path.join(TEMP_DIR, "input.pdf")
        output_path = os.path.join(TEMP_DIR, "output.pdf")

        with open(input_path, "wb") as f:
            f.write(resp.content)

        # OCR first
        try:
            ocrmypdf.ocr(
                input_path,
                output_path,
                deskew=True,
                skip_text=True,
                optimize=2,
                language="eng",
            )
            pdf_path = output_path
        except ocrmypdf.exceptions.PriorOcrFoundError:
            pdf_path = input_path

        # Extract text with PyMuPDF
        doc = fitz.open(pdf_path)
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

    except httpx.HTTPError as e:
        raise HTTPException(status_code=400, detail=f"Failed to download PDF: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
