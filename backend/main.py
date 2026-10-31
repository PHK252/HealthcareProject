from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
import sqlite3
import pymupdf
import re
import uuid
import httpx
import json
from typing import Optional
from pydantic import BaseModel, Field
from typing import Literal
import unicodedata


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


# --------------------------------------------------
# DATABASE SETUP
# --------------------------------------------------

DATABASE_PATH = Path(__file__).resolve().parent / "carebridge.db"


def get_db():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database():
    with get_db() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                page_count INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS care_tasks (
                task_id TEXT PRIMARY KEY,
                document_id INTEGER NOT NULL,
                suggested_text TEXT NOT NULL,
                source_quote TEXT NOT NULL,
                page INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'needs_review',
                method TEXT NOT NULL,
                FOREIGN KEY (document_id)
                    REFERENCES documents(id)
                    ON DELETE CASCADE
            )
        """)

    # Add completion tracking to databases created by earlier versions.
    columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(care_tasks)"
            ).fetchall()
        }

    if "completed" not in columns:
            connection.execute("""
                ALTER TABLE care_tasks
                ADD COLUMN completed INTEGER NOT NULL DEFAULT 0
            """)


initialize_database()


# --------------------------------------------------
# MODELS
# --------------------------------------------------

class TaskStatusUpdate(BaseModel):
    status: str

class TaskCompletionUpdate(BaseModel):
    completed: bool

class CareTaskCandidate(BaseModel):
    task_text: str
    category: Literal[
        "medication",
        "appointment",
        "follow_up",
        "activity_restriction",
        "wound_care",
        "symptom_monitoring",
        "warning_sign",
        "other",
    ]
    due_date: Optional[str] = None
    source_quote: str
    confidence: float = Field(ge=0.0, le=1.0)
    needs_review: bool = True


class CareTaskExtraction(BaseModel):
    tasks: list[CareTaskCandidate]


async def extract_tasks_with_ollama(pages: list[dict]) -> dict:
    verified_tasks = []
    rejected_tasks = []

    async with httpx.AsyncClient(timeout=120.0) as client:

        for page in pages:
            page_text = page["text"]

            if not page_text.strip():
                continue

            prompt = f"""
You extract actionable care instructions from a discharge document.

Extract only instructions explicitly present in the supplied text.

Categories:
- medication
- appointment
- follow_up
- activity_restriction
- wound_care
- symptom_monitoring
- warning_sign
- other

Rules:
1. Copy source_quote EXACTLY from the supplied text.
2. Never invent or paraphrase source_quote.
3. Do not create instructions that are not explicitly stated.
4. Do not extract general background information as a task.
5. Conditional instructions may be included, but set needs_review=true.
6. Do not invent medication instructions or due dates.
7. Only use a due_date when the text explicitly provides a timeframe or date.
8. Keep task_text faithful to the original instruction.
9. Return an empty tasks list if no actionable instructions exist.

TEXT:
{page_text}
"""

            response = await client.post(
                "http://localhost:11434/api/chat",
                json={
                    "model": "llama3.2",
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are a precise extraction system. "
                                "Return only JSON matching the supplied schema."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "format": CareTaskExtraction.model_json_schema(),
                    "stream": False,
                    "options": {"temperature": 0},
                },
            )

            response.raise_for_status()

            content = response.json()["message"]["content"]

            extraction = CareTaskExtraction.model_validate_json(content)

            for task in extraction.tasks:

                normalized_page = normalize_text(page_text)
                normalized_quote = normalize_text(task.source_quote)

                if (
                    normalized_quote
                    and normalized_quote in normalized_page
                ):
                    verified_tasks.append({
                        **task.model_dump(),
                        "page": page["page"],
                        "confidence": 0.8,
                        "needs_review": True,
                    })
                else:
                    rejected_tasks.append({
                        **task.model_dump(),
                        "page": page["page"],
                        "reason": "Source quotation not found on original page",
                    })

    return {
        "tasks": verified_tasks,
        "rejected_count": len(rejected_tasks),
        "rejected_tasks": rejected_tasks,
    }

# --------------------------------------------------
# BASIC ENDPOINTS
# --------------------------------------------------

@app.get("/")
def root():
    return {"message": "Welcome to CareBridge"}


@app.get("/health")
def health_check():
    return {"status": "ok"}


# --------------------------------------------------
# TASK EXTRACTION
# --------------------------------------------------

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
        segments = re.split(
            r"(?<=[.!?])\s+|\n+",
            page["text"],
        )

        for segment in segments:
            quote = segment.strip()

            if not quote or not patterns.search(quote):
                continue

            candidates.append({
                "task_id": str(uuid.uuid4()),
                "suggested_text": quote,
                "source_quote": quote,
                "page": page["page"],
                "status": "needs_review",
                "method": "rule_based",
            })

    return candidates


# --------------------------------------------------
# DOCUMENT EXTRACTION AND STORAGE
# --------------------------------------------------

@app.post("/documents/extract")
async def extract_document(file: UploadFile = File(...)):

    if file.content_type != "application/pdf":
        raise HTTPException(
            status_code=400,
            detail="Please upload a PDF file.",
        )

    contents = await file.read()

    if not contents:
        raise HTTPException(
            status_code=400,
            detail="The file is empty.",
        )

    try:
        with pymupdf.open(
            stream=contents,
            filetype="pdf",
        ) as document:
            pages = [
                {
                    "page": page_number,
                    "text": page.get_text().strip(),
                }
                for page_number, page in enumerate(document, start=1)
            ]
            print("\n========== EXTRACTED PDF TEXT ==========")

            for page in pages:
                print(f"\nPAGE {page['page']}:")
                print(page["text"])

            print("\n========================================")

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

    # Save the document and its tasks together.
    with get_db() as connection:

        cursor = connection.execute(
            """
            INSERT INTO documents (filename, page_count)
            VALUES (?, ?)
            """,
            (file.filename or "unnamed.pdf", len(pages)),
        )

        document_id = cursor.lastrowid

        for task in task_candidates:
            connection.execute(
                """
                INSERT INTO care_tasks (
                    task_id,
                    document_id,
                    suggested_text,
                    source_quote,
                    page,
                    status,
                    method
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task["task_id"],
                    document_id,
                    task["suggested_text"],
                    task["source_quote"],
                    task["page"],
                    task["status"],
                    task["method"],
                ),
            )

    return {
        "document_id": document_id,
        "filename": file.filename,
        "page_count": len(pages),
        "pages": pages,
        "text": extracted_text,
        "task_candidates": task_candidates,
    }


# --------------------------------------------------
# RETRIEVE SAVED DOCUMENTS
# --------------------------------------------------

@app.get("/documents")
def get_documents():

    with get_db() as connection:
        rows = connection.execute(
            """
            SELECT id, filename, page_count, created_at
            FROM documents
            ORDER BY id DESC
            """
        ).fetchall()

    return [dict(row) for row in rows]


# --------------------------------------------------
# RETRIEVE SAVED TASKS
# --------------------------------------------------

@app.get("/tasks")
def get_tasks():

    with get_db() as connection:
        rows = connection.execute(
            """
            SELECT
                task_id,
                document_id,
                suggested_text,
                source_quote,
                page,
                status,
                method,
                completed
            FROM care_tasks
            ORDER BY rowid
            """
        ).fetchall()

    return [dict(row) for row in rows]


# --------------------------------------------------
# UPDATE TASK REVIEW STATUS
# --------------------------------------------------

@app.patch("/tasks/{task_id}")
def update_task_status(task_id: str, update: TaskStatusUpdate):

    allowed_statuses = {
        "needs_review",
        "confirmed",
        "rejected",
    }

    if update.status not in allowed_statuses:
        raise HTTPException(
            status_code=400,
            detail="Invalid task status.",
        )

    with get_db() as connection:
        cursor = connection.execute(
            """
            UPDATE care_tasks
            SET status = ?
            WHERE task_id = ?
            """,
            (update.status, task_id),
        )

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="Task not found.",
            )

    return {
        "task_id": task_id,
        "status": update.status,
    }

@app.patch("/tasks/{task_id}/completion")
def update_task_completion(
    task_id: str,
    update: TaskCompletionUpdate
):
    with get_db() as connection:
        cursor = connection.execute(
            """
            UPDATE care_tasks
            SET completed = ?
            WHERE task_id = ?
            AND status = 'confirmed'
            """,
            (int(update.completed), task_id),
        )

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="Confirmed task not found.",
            )

    return {
        "task_id": task_id,
        "completed": update.completed,
    }

@app.post("/documents/extract-llm")
async def extract_document_with_llm(file: UploadFile = File(...)):
    if file.content_type != "application/pdf":
        raise HTTPException(
            status_code=400,
            detail="Please upload a PDF file."
        )

    contents = await file.read()

    try:
        pdf = pymupdf.open(stream=contents, filetype="pdf")

        pages = [
            {
                "page": page_number + 1,
                "text": page.get_text(),
            }
            for page_number, page in enumerate(pdf)
        ]

        pdf.close()

    except Exception as error:
        raise HTTPException(
            status_code=400,
            detail=f"Could not read PDF: {str(error)}"
        )

    if not any(page["text"].strip() for page in pages):
        raise HTTPException(
            status_code=422,
            detail="This PDF contains no selectable text. OCR is needed."
        )

    try:
        extraction = await extract_tasks_with_ollama(pages)
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=f"LLM extraction failed: {str(error)}"
        )

    return {
        "filename": file.filename,
        "page_count": len(pages),
        "method": "ollama_llama3.2",
        **extraction,
    }

def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()