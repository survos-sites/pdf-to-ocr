# PDF-to-OCR Microservice

A FastAPI service that accepts a PDF URL, runs OCRmyPDF (Tesseract), and
provides searchable PDFs, extracted text, page images, and thumbnails — all
from a single service.

## Endpoints

| Endpoint | Returns | Use case |
|---|---|---|
| `GET /ocr?url=...` | Searchable PDF | Store the OCR'd PDF back to S3 |
| `GET /text?url=...` | JSON per-page text | Index into Meilisearch |
| `GET /page-image?url=...&page=1&dpi=200` | PNG image | On-demand full-res page view |
| `GET /thumbnail?url=...&page=1` | PNG thumbnail (72 DPI) | Browse/preview UI |

All endpoints accept a `url` parameter pointing to a PDF (e.g. an S3
presigned URL). The PDF is downloaded once, OCR'd once, and cached — so
calling `/text` after `/ocr` for the same URL is nearly instant.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OCR_LANGUAGE` | `eng` | Tesseract language(s), e.g. `eng+spa` |
| `PORT` | `5000` | Set automatically by Dokku |

## Deploy to Dokku

### 1. Create the app

```bash
ssh dokku@your-server apps:create pdf-to-ocr
```

### 2. Set the domain

```bash
ssh dokku@your-server domains:set pdf-to-ocr pdftoocr.survos.com
```

### 3. Configure language support (optional)

```bash
ssh dokku@your-server config:set pdf-to-ocr OCR_LANGUAGE=eng+spa
```

### 4. Push to deploy

Dokku auto-detects the Dockerfile and builds from it.

```bash
cd pdf-to-ocr
git init
git add .
git commit -m "initial"
git remote add dokku dokku@your-server:pdf-to-ocr
git push dokku main
```

### 5. Enable HTTPS

```bash
ssh dokku@your-server letsencrypt:enable pdf-to-ocr
```

### 6. Increase timeouts for large PDFs

```bash
ssh dokku@your-server nginx:set pdf-to-ocr proxy-read-timeout 300s
ssh dokku@your-server nginx:set pdf-to-ocr proxy-send-timeout 300s
ssh dokku@your-server ps:rebuild pdf-to-ocr
```

### 7. Increase body size limit (if uploading large PDFs later)

```bash
ssh dokku@your-server nginx:set pdf-to-ocr client-max-body-size 50m
ssh dokku@your-server ps:rebuild pdf-to-ocr
```

## Usage Examples

```bash
# Get a searchable PDF back
curl -o result.pdf "https://pdftoocr.survos.com/ocr?url=https://example.com/scan.pdf"

# Get extracted text as JSON (for Meilisearch indexing)
curl "https://pdftoocr.survos.com/text?url=https://example.com/scan.pdf"

# Get page 3 as a high-res PNG
curl -o page3.png "https://pdftoocr.survos.com/page-image?url=https://example.com/scan.pdf&page=3&dpi=300"

# Get a thumbnail of the first page
curl -o thumb.png "https://pdftoocr.survos.com/thumbnail?url=https://example.com/scan.pdf"
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

## ScanStationAI Workflow

1. **Appliance** scans documents → uploads raw PDF to S3
2. **Symfony** calls `/ocr?url=s3-presigned-url` → stores searchable PDF back to S3
3. **Symfony** calls `/text?url=s3-url-of-ocr-pdf` → indexes per-page text in Meilisearch
4. **UI** calls `/thumbnail` and `/page-image` on demand when user browses documents

No need to pre-split PDFs into individual images — pages are rendered on
the fly when requested.

## Local Development

```bash
pip install -r requirements.txt
# Needs tesseract and ghostscript installed:
# macOS: brew install tesseract ghostscript
# Ubuntu: apt install tesseract-ocr ghostscript
uvicorn app:app --reload --port 5000
```

## Future Enhancements

- Return a task ID for async processing (Redis + Celery or Symfony Messenger)
- Accept S3 paths directly instead of URLs
- Store OCR'd PDFs back to S3 automatically
- Webhook callback when OCR is complete
