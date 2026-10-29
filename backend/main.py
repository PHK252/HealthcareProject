
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
import pymupdf
import re


app = FastAPI(title="CareBridge API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"message": "Welcome to CareBridge"}


@app.get("/health")
def health_check():
    return {"status": "ok"}


def identify_task_candidates(pages):
    """Find possible care tasks and preserve their original source."""

    patterns = re.compile(
        r"\b("
        r"follow[- ]up|appointment|schedule|contact|call|"
        r"refer(?:red|ral)?|monitor|avoid|return|"
        r"seek|prescription|medication|keep .* in place|"
        r"arrange|confirm"
        r")\b",
        re.IGNORECASE,
    )

    candidates = []

    for page in pages:
        # Split page text into sentence-like segments.
        segments = re.split(
            r"(?<=[.!?])\s+|\n+",
            page["text"],
        )

        for segment in segments:
            quote = segment.strip()

            if not quote or not patterns.search(quote):
                continue

            candidates.append({
                "task_id": f"task-{len(candidates) + 1}",
                "suggested_text": quote,
                "source_quote": quote,
                "page": page["page"],
                "status": "needs_review",
                "method": "rule_based",
            })

    return candidates



@app.post("/documents/extract")
async def extract_document(file: UploadFile = File(...)):
    if file.content_type != "application/pdf":
        raise HTTPException(
            status_code=400,
            detail="Please upload a PDF file.",
        )

    contents = await file.read()

    if not contents:
        raise HTTPException(status_code=400, detail="The file is empty.")

    try:
        with pymupdf.open(stream=contents, filetype="pdf") as document:
            pages = [
                {
                    "page": page_number,
                    "text": page.get_text().strip(),
                }
                for page_number, page in enumerate(document, start=1)
            ]
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Could not read this PDF.",
        )

    extracted_text = "\n\n".join(
        f"[Page {page['page']}]\n{page['text']}"
        for page in pages
        if page["text"]
    )

    if not extracted_text.strip():
        raise HTTPException(
            status_code=422,
            detail=(
                "No selectable text was found. "
                "This PDF may be a scan and need OCR."
            ),
        )

    task_candidates = identify_task_candidates(pages)

    return {
        "filename": file.filename,
        "page_count": len(pages),
        "pages": pages,
        "text": extracted_text,
        "task_candidates": task_candidates,
    }