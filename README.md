# PDF-to-OCR Microservice

A simple FastAPI service that accepts a PDF URL, runs OCRmyPDF, and returns
either the searchable PDF or extracted text as JSON.

## Endpoints

- `GET /` — health check
- `GET /ocr?url=https://...pdf` — returns searchable PDF file
- `GET /text?url=https://...pdf` — returns JSON with per-page text

## Deploy to Dokku

### 1. Create the app on your Dokku server

```bash
ssh dokku@your-server apps:create pdf-to-ocr
```

### 2. Set the domain

```bash
ssh dokku@your-server domains:set pdf-to-ocr pdftoocr.survos.com
```

### 3. Push to deploy (Dockerfile-based)

Dokku auto-detects the Dockerfile and builds from it. This is the
recommended approach since OCRmyPDF needs Tesseract and Ghostscript
at the system level.

```bash
cd pdf-to-ocr
git init
git add .
git commit -m "initial"
git remote add dokku dokku@your-server:pdf-to-ocr
git push dokku main
```

### 4. Enable HTTPS (Let's Encrypt)

```bash
ssh dokku@your-server letsencrypt:enable pdf-to-ocr
```

### 5. (Optional) Increase timeout for large PDFs

```bash
ssh dokku@your-server proxy:set pdf-to-ocr nginx-read-timeout 300
ssh dokku@your-server proxy:set pdf-to-ocr nginx-send-timeout 300
# Or for older Dokku versions:
ssh dokku@your-server nginx:set pdf-to-ocr proxy-read-timeout 300s
```

### 6. (Optional) Increase upload/body size limit

```bash
ssh dokku@your-server nginx:set pdf-to-ocr client-max-body-size 50m
```

## Usage

```bash
# Get a searchable PDF back
curl -o result.pdf "https://pdftoocr.survos.com/ocr?url=https://example.com/scan.pdf"

# Get extracted text as JSON
curl "https://pdftoocr.survos.com/text?url=https://example.com/scan.pdf"
```

## Response format for /text

```json
{
  "url": "https://example.com/scan.pdf",
  "page_count": 3,
  "pages": [
    {"page": 1, "text": "First page content..."},
    {"page": 2, "text": "Second page content..."},
    {"page": 3, "text": "Third page content..."}
  ]
}
```

## Notes

- OCRmyPDF uses `--skip-text` so PDFs that already have OCR are passed through quickly.
- The `--deskew` flag straightens slightly rotated scans.
- Spanish (`tesseract-ocr-spa`) is pre-installed; add more languages in the Dockerfile.
- For production, you'll want to add task queuing (Celery/Redis) for large PDFs
  and return a task ID instead of blocking.
