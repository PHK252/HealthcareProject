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
import math
from collections import Counter


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
        
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS document_chunks (
                chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                page INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                FOREIGN KEY (document_id)
                    REFERENCES documents(id)
                    ON DELETE CASCADE
            )
            """
        )
        

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

    # Add structured LLM extraction fields.
    columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(care_tasks)"
        ).fetchall()
    }

    if "category" not in columns:
        connection.execute("""
            ALTER TABLE care_tasks
            ADD COLUMN category TEXT NOT NULL DEFAULT 'other'
        """)

    if "due_date" not in columns:
        connection.execute("""
            ALTER TABLE care_tasks
            ADD COLUMN due_date TEXT
        """)

    if "confidence" not in columns:
        connection.execute("""
            ALTER TABLE care_tasks
            ADD COLUMN confidence REAL NOT NULL DEFAULT 0.0
        """)

    if "needs_review" not in columns:
        connection.execute("""
            ALTER TABLE care_tasks
            ADD COLUMN needs_review INTEGER NOT NULL DEFAULT 1
        """)        


initialize_database()


# --------------------------------------------------
# MODELS
# --------------------------------------------------

class QuestionRequest(BaseModel):
    question: str

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

@app.post("/documents/{document_id}/ask")
async def ask_document_question(
    document_id: int,
    request: QuestionRequest,
):
    question = request.question.strip()

    if not question:
        raise HTTPException(
            status_code=400,
            detail="Please enter a question.",
        )

    # Verify that the document exists.
    with get_db() as connection:
        document = connection.execute(
            "SELECT id FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()

    if document is None:
        raise HTTPException(
            status_code=404,
            detail="Document not found.",
        )

    return await answer_question_with_rag(
        question=question,
        document_id=document_id,
    )


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

    # Try LLM extraction first.
    extraction_warning = None

    try:
        llm_result = await extract_tasks_with_ollama(pages)

        task_candidates = []

        for task in llm_result["tasks"]:
            task_candidates.append({
                "task_id": str(uuid.uuid4()),
                "suggested_text": task["task_text"],
                "source_quote": task["source_quote"],
                "page": task["page"],
                "status": "needs_review",
                "method": "ollama_llama3.2",
                "completed": False,
                "category": task["category"],
                "due_date": task["due_date"],
                "confidence": task["confidence"],
                "needs_review": True,
            })

        extraction_method = "ollama_llama3.2"

    except Exception as error:
        # Fall back to the original rule-based extractor.
        print(f"Ollama extraction failed: {error}")

        extraction_warning = (
            "LLM extraction was unavailable. "
            "Rule-based extraction was used instead."
        )

        task_candidates = identify_task_candidates(pages)

        for task in task_candidates:
            task.update({
                "category": "other",
                "due_date": None,
                "confidence": 0.0,
                "needs_review": True,
                "completed": False,
            })

        extraction_method = "rule_based"

    # Save the document and its tasks together.
    # Split extracted pages into searchable chunks.
    document_chunks = chunk_document_pages(pages)

    # Save the document, its tasks, and its chunks together.
    with get_db() as connection:

        cursor = connection.execute(
            """
            INSERT INTO documents (filename, page_count)
            VALUES (?, ?)
            """,
            (file.filename or "unnamed.pdf", len(pages)),
        )

        document_id = cursor.lastrowid

        # Save task candidates.
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
                    method,
                    category,
                    due_date,
                    confidence,
                    needs_review,
                    completed
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task["task_id"],
                    document_id,
                    task["suggested_text"],
                    task["source_quote"],
                    task["page"],
                    task["status"],
                    task["method"],
                    task["category"],
                    task["due_date"],
                    task["confidence"],
                    int(task["needs_review"]),
                    int(task["completed"]),
                ),
            )

        # Save searchable document chunks.
        for chunk in document_chunks:
            connection.execute(
                """
                INSERT INTO document_chunks (
                    document_id,
                    page,
                    chunk_index,
                    content
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    document_id,
                    chunk["page"],
                    chunk["chunk_index"],
                    chunk["content"],
                ),
            )

    return {
        "document_id": document_id,
        "chunk_count": len(document_chunks),
        "filename": file.filename,
        "page_count": len(pages),
        "pages": pages,
        "text": extracted_text,
        "task_candidates": task_candidates,
        "extraction_method": extraction_method,
        "extraction_warning": extraction_warning,
    }

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
                completed,
                category,
                due_date,
                confidence,
                needs_review
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

def chunk_document_pages(
    pages: list[dict],
    chunk_size: int = 800,
    overlap: int = 150,
) -> list[dict]:
    """
    Split document pages into overlapping text chunks.

    chunk_size and overlap are measured in characters.
    Each chunk retains its original page number.
    """
    chunks = []

    for page in pages:
        text = normalize_text(page["text"])

        if not text:
            continue

        start = 0
        chunk_index = 0

        while start < len(text):
            end = min(start + chunk_size, len(text))

            # Prefer ending at a word boundary.
            if end < len(text):
                boundary = text.rfind(" ", start, end)
                if boundary > start:
                    end = boundary

            content = text[start:end].strip()

            if content:
                chunks.append({
                    "page": page["page"],
                    "chunk_index": chunk_index,
                    "content": content,
                })

                chunk_index += 1

            if end >= len(text):
                break

            start = max(end - overlap, start + 1)

    return chunks

def retrieve_relevant_chunks(
    query: str,
    top_k: int = 3,
    document_id: int | None = None,
) -> list[dict]:
    """
    Retrieve the most relevant document chunks using BM25 scoring.
    Optionally restrict retrieval to one uploaded document.
    """

    stop_words = {
        "the", "a", "an", "is", "are", "was", "were",
        "to", "of", "in", "on", "for", "and", "or",
        "with", "what", "when", "where", "how", "do",
        "does", "i", "my", "me", "you", "your",
        "should", "can", "could", "would"
    }

    def tokenize(text: str) -> list[str]:
        words = re.findall(r"\b[a-zA-Z0-9]+\b", text.lower())
        return [word for word in words if word not in stop_words]

    query_terms = tokenize(query)

    if not query_terms:
        return []

    with get_db() as connection:
        rows = connection.execute(
            """
            SELECT
                dc.chunk_id,
                dc.document_id,
                dc.page,
                dc.chunk_index,
                dc.content,
                d.filename
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE (? IS NULL OR dc.document_id = ?)
            """,
            (document_id, document_id),
        ).fetchall()

    if not rows:
        return []

    documents = []

    for row in rows:
        content = row["content"]
        tokens = tokenize(content)

        documents.append({
            "chunk_id": row["chunk_id"],
            "document_id": row["document_id"],
            "page": row["page"],
            "chunk_index": row["chunk_index"],
            "filename": row["filename"],
            "content": content,
            "tokens": tokens,
            "term_counts": Counter(tokens),
        })

    total_documents = len(documents)
    average_length = sum(
        len(doc["tokens"]) for doc in documents
    ) / total_documents

    # BM25 parameters.
    k1 = 1.5
    b = 0.75

    # Count how many chunks contain each query term.
    document_frequency = {}

    for term in set(query_terms):
        document_frequency[term] = sum(
            1 for doc in documents
            if doc["term_counts"][term] > 0
        )

    # Score each chunk.
    for doc in documents:
        score = 0.0
        length = len(doc["tokens"])

        for term in query_terms:
            frequency = doc["term_counts"][term]

            if frequency == 0:
                continue

            df = document_frequency[term]

            idf = math.log(
                1 + (total_documents - df + 0.5) / (df + 0.5)
            )

            denominator = frequency + k1 * (
                1 - b + b * length / average_length
            )

            score += idf * (
                frequency * (k1 + 1) / denominator
            )

        doc["score"] = score

    # Highest scoring chunks first.
    results = sorted(
        documents,
        key=lambda doc: doc["score"],
        reverse=True,
    )

    # Remove internal scoring data from the response.
    return [
        {
            "chunk_id": doc["chunk_id"],
            "document_id": doc["document_id"],
            "filename": doc["filename"],
            "page": doc["page"],
            "content": doc["content"],
            "score": round(doc["score"], 4),
        }
        for doc in results[:top_k]
        if doc["score"] > 0
    ]

async def answer_question_with_rag(
    question: str,
    document_id: int,
) -> dict:

    # Retrieve relevant passages from this document.
    chunks = retrieve_relevant_chunks(
        query=question,
        top_k=3,
        document_id=document_id,
    )

    if not chunks:
        return {
            "answer": (
                "I couldn't find relevant information "
                "in this document to answer that question."
            ),
            "sources": [],
        }

    # Label each passage so the model can cite its evidence.
    context = "\n\n".join(
        f"[Source {index + 1} | Page {chunk['page']}]\n"
        f"{chunk['content']}"
        for index, chunk in enumerate(chunks)
    )

    prompt = f"""
You are a document question-answering assistant for CareBridge.

Answer the user's question using ONLY the supplied document passages.

Rules:
- Do not invent medical instructions or facts.
- Do not use outside medical knowledge to fill gaps.
- If the passages do not contain the answer, say so clearly.
- Preserve important dates, quantities, and conditions exactly.
- Cite supporting passages using [Source 1], [Source 2], etc.
- Distinguish explicit instructions from general information.
- Remind the user to consult their healthcare professional
  when the document is unclear.

DOCUMENT PASSAGES:

{context}

USER QUESTION:

{question}
"""

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                "http://localhost:11434/api/chat",
                json={
                    "model": "llama3.2",
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You answer questions using only "
                                "provided document evidence."
                            ),
                        },
                        {
                            "role": "user",
                            "content": prompt,
                        },
                    ],
                    "stream": False,
                    "options": {
                        "temperature": 0,
                    },
                },
            )

            response.raise_for_status()

            answer = response.json()["message"]["content"]

    except Exception as error:
        print(f"RAG answer generation failed: {error}")
        raise HTTPException(
            status_code=503,
            detail="The local language model is unavailable.",
        )

    sources = [
        {
            "source": index + 1,
            "document_id": chunk["document_id"],
            "filename": chunk["filename"],
            "page": chunk["page"],
            "content": chunk["content"],
        }
        for index, chunk in enumerate(chunks)
    ]

    return {
        "answer": answer,
        "sources": sources,
    }


# if __name__ == "__main__":
#     test_pages = [
#         {
#             "page": 1,
#             "text": "Take your medication every morning. "
#                     "Schedule a follow-up appointment within two weeks."
#         }
#     ]

#     test_chunks = chunk_document_pages(
#         test_pages,
#         chunk_size=60,
#         overlap=15,
#     )

#     for chunk in test_chunks:
#         print(chunk)