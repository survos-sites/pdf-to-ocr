# PDF-to-OCR Microservice

A FastAPI service that accepts a PDF URL, runs OCRmyPDF with Tesseract, and
provides searchable PDFs, extracted text, page images, and thumbnails. It also
supports materializing an ordered list of JPG scans into a searchable PDF/A.

## Endpoints

| Endpoint | Returns | Use case |
|---|---|---|
| `GET /ocr?url=...` | Searchable PDF | Store the OCR'd PDF back to S3 |
| `POST /materialize` | Searchable PDF/A bytes | Build a PDF/A from ordered JPG URLs |
| `GET /text?url=...` | JSON per-page text | Index into Meilisearch |
| `GET /page-image?url=...&page=1&dpi=200` | PNG image | On-demand full-res page view |
| `GET /thumbnail?url=...&page=1` | PNG thumbnail (72 DPI) | Browse/preview UI |

All endpoints accept a `url` parameter pointing to a PDF (e.g. an S3
presigned URL). The PDF is downloaded once, OCR'd once, and cached — so
calling `/text` after `/ocr` for the same URL is nearly instant.

`POST /materialize` is different: it accepts a JSON payload with an ordered
list of JPG URLs, downloads them into a temporary working directory, assembles
them losslessly with `img2pdf`, then runs OCRmyPDF to emit a searchable
`PDF/A-2` document.

## OCR Engine Notes

`ocrmypdf` is the pipeline coordinator, not the OCR engine itself.

- OCR engine: `Tesseract`
- PDF/image rasterizer in OCRmyPDF 17.x: `pypdfium2` by default
- Page cleanup for `clean_final=True`: `unpaper`
- PDF assembly and metadata handling: `pikepdf`

For `POST /materialize`, the expensive step is still Tesseract OCR. Downloading
JPGs from colocated object storage should usually be fast; OCR and PDF/A
conversion dominate latency on larger jobs.

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

# Build a searchable PDF/A from ordered JPG scans
curl \
  -X POST "https://pdftoocr.survos.com/materialize" \
  -H "Content-Type: application/json" \
  -o materialized.pdf \
  -d '{
    "image_urls": [
      "https://example.com/page-0001.jpg",
      "https://example.com/page-0002.jpg"
    ],
    "title": "Example scan",
    "author": "Survos",
    "keywords": "scan,materialized",
    "language": "eng"
  }'

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

## Request Format for /materialize

```json
{
  "image_urls": [
    "https://example.com/page-0001.jpg",
    "https://example.com/page-0002.jpg"
  ],
  "title": "Example scan",
  "author": "Survos",
  "keywords": "archive,scan",
  "language": "eng"
}
```

Field notes:

- `image_urls` is required and order-sensitive.
- Images are downloaded as `page_0000.jpg`, `page_0001.jpg`, and so on.
- `language` defaults to `OCR_LANGUAGE` or `eng`.
- `title`, `author`, and `keywords` are written into the output PDF metadata.

## PDF/A and Metadata

The materialized output is written as `PDF/A-2`, which is an archival subset of
PDF intended for long-term preservation. In practice that means the file is
self-contained and avoids fragile features that make future rendering less
reliable.

Metadata is carried into the output document through OCRmyPDF. The current
endpoint supports:

- `title`
- `author`
- `keywords`

These fields improve indexing, recordkeeping, and downstream archival workflows.
`language` affects OCR behavior and may inform document language tagging, but it
is not the same as descriptive metadata like title or author.

## Performance Notes

Current behavior is synchronous and blocking per request.

- Downloading JPGs from Hetzner object storage should be relatively fast when
  the service and bucket are colocated.
- `img2pdf` preserves the original JPEG data losslessly and is usually fast.
- Tesseract OCR is the main latency source.
- Returning a large PDF over HTTP is acceptable for now, but storing the result
  in object storage and returning a URL is a better fit for larger jobs.

For current expected volume, Dokku timeouts of `300s` are acceptable. If scan
materialization becomes large or frequent, move to an S3-backed output flow.

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

- Accept `image_urls` plus precomputed OCR text in JSON so this service can
  skip Tesseract for scan materialization
- Store materialized PDF/A back to S3 automatically and return a URL/object key
- Return a task ID for async processing (Redis + Celery or Symfony Messenger)
- Accept S3 paths directly instead of URLs
- Store OCR'd PDFs back to S3 automatically
- Webhook callback when OCR is complete

## Future Request Shape for Precomputed OCR

When scan OCR is produced upstream, the better contract is likely a second
materialization payload that carries both ordered JPG URLs and ordered OCR text.
That would move OCR outside this request path and make real-time materialization
much more plausible.

Example shape:

```json
{
  "pages": [
    {
      "image_url": "https://example.com/page-0001.jpg",
      "ocr_text": "First page text"
    },
    {
      "image_url": "https://example.com/page-0002.jpg",
      "ocr_text": "Second page text"
    }
  ],
  "title": "Example scan",
  "author": "Survos",
  "keywords": "archive,scan",
  "language": "eng"
}
```

That path would require a different implementation than `ocrmypdf.ocr()`,
because OCRmyPDF expects to run OCR itself rather than consume precomputed text.
