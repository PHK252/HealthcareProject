from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
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
import os
import boto3
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import RowMapping
from sqlalchemy import (
    MetaData, Table, Column, Integer, String, Text,
    DateTime, Float, ForeignKey, Identity, inspect, text
)



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

# Load environment variables before reading configuration
load_dotenv(Path(__file__).resolve().parent / ".env")

# Database configuration
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{DATABASE_PATH}"
)

# SQLAlchemy database engine
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)

AWS_REGION = os.getenv("AWS_REGION", "us-east-2")

S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")

if not S3_BUCKET_NAME:
    raise RuntimeError("S3_BUCKET_NAME is not configured.")

# Initialize S3 client using local AWS credentials
s3_client = boto3.client(
    "s3",
    region_name=AWS_REGION
)

def upload_pdf_to_s3(
    file_content: bytes,
    document_id: int,
    filename: str
) -> str:
    """
    Upload an original PDF to S3 and return its object key.
    """

    object_key = f"documents/{document_id}/{filename}"

    s3_client.put_object(
        Bucket=S3_BUCKET_NAME,
        Key=object_key,
        Body=file_content,
        ContentType="application/pdf"
    )

    return object_key



def initialize_database():
    metadata = MetaData()

    # Documents table
    Table(
        "documents",
        metadata,
        Column("id", Integer, Identity(), primary_key=True),
        Column("filename", String, nullable=False),
        Column("page_count", Integer, nullable=False),
        Column(
            "created_at",
            DateTime,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
        Column("s3_key", Text),
    )

    # Care tasks table
    Table(
        "care_tasks",
        metadata,
        Column("task_id", String, primary_key=True),
        Column(
            "document_id",
            Integer,
            ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        Column("suggested_text", Text, nullable=False),
        Column("source_quote", Text, nullable=False),
        Column("page", Integer, nullable=False),
        Column(
            "status",
            String,
            nullable=False,
            server_default=text("'needs_review'"),
        ),
        Column("method", String, nullable=False),
        Column("completed", Integer, nullable=False, server_default=text("0")),
        Column(
            "category",
            String,
            nullable=False,
            server_default=text("'other'"),
        ),
        Column("due_date", Text),
        Column("confidence", Float, nullable=False, server_default=text("0.0")),
        Column("needs_review", Integer, nullable=False, server_default=text("1")),
    )

    # Document chunks table
    Table(
        "document_chunks",
        metadata,
        Column("chunk_id", Integer, Identity(), primary_key=True),
        Column(
            "document_id",
            Integer,
            ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        Column("page", Integer, nullable=False),
        Column("chunk_index", Integer, nullable=False),
        Column("content", Text, nullable=False),
    )

    # Create tables that do not already exist.
    metadata.create_all(engine)

    # Add missing columns to older databases without deleting data.
    migrations = {
        "documents": {
            "s3_key": "TEXT",
        },
        "care_tasks": {
            "completed": "INTEGER NOT NULL DEFAULT 0",
            "category": "TEXT NOT NULL DEFAULT 'other'",
            "due_date": "TEXT",
            "confidence": "REAL NOT NULL DEFAULT 0.0",
            "needs_review": "INTEGER NOT NULL DEFAULT 1",
        },
    }

    inspector = inspect(engine)

    with engine.begin() as connection:
        for table_name, columns_to_add in migrations.items():
            existing_columns = {
                column["name"]
                for column in inspector.get_columns(table_name)
            }

            for column_name, column_definition in columns_to_add.items():
                if column_name not in existing_columns:
                    connection.execute(
                        text(
                            f"ALTER TABLE {table_name} "
                            f"ADD COLUMN {column_name} {column_definition}"
                        )
                    )

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
    with engine.connect() as connection:
        result = connection.execute(
            text("""
                SELECT id
                FROM documents
                WHERE id = :document_id
            """),
            {"document_id": document_id},
        )

        document = result.mappings().first()

    if document is None:
        raise HTTPException(
            status_code=404,
            detail="Document not found.",
        )

    return await answer_question_with_rag(
        question=question,
        document_id=document_id,
    )
@app.delete("/documents/{document_id}")
async def delete_document(document_id: int):

    # First, retrieve the document's S3 key.
    with engine.connect() as connection:
        result = connection.execute(
            text("""
                SELECT id, s3_key
                FROM documents
                WHERE id = :document_id
            """),
            {"document_id": document_id},
        )

        document = result.mappings().first()

    if document is None:
        raise HTTPException(
            status_code=404,
            detail="Document not found.",
        )

    # Delete the original PDF from S3 first.
    s3_key = document["s3_key"]

    if s3_key:
        try:
            s3_client.delete_object(
                Bucket=S3_BUCKET_NAME,
                Key=s3_key,
            )
        except Exception as error:
            print(f"S3 deletion failed: {error}")

            raise HTTPException(
                status_code=500,
                detail="Could not delete the original PDF from storage.",
            )

    # Remove associated database records in one transaction.
    with engine.begin() as connection:

        connection.execute(
            text("""
                DELETE FROM care_tasks
                WHERE document_id = :document_id
            """),
            {"document_id": document_id},
        )

        connection.execute(
            text("""
                DELETE FROM document_chunks
                WHERE document_id = :document_id
            """),
            {"document_id": document_id},
        )

        connection.execute(
            text("""
                DELETE FROM documents
                WHERE id = :document_id
            """),
            {"document_id": document_id},
        )

    return {
        "message": "Document deleted successfully.",
        "document_id": document_id,
    }

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

    # Split extracted pages into searchable chunks.
    document_chunks = chunk_document_pages(pages)

    # Prepare the S3 filename.
    safe_filename = Path(file.filename or "unnamed.pdf").name

    # Save the document, tasks, and chunks together.
    with engine.begin() as connection:

        # Insert document and retrieve its generated ID.
        result = connection.execute(
            text("""
                INSERT INTO documents (filename, page_count)
                VALUES (:filename, :page_count)
                RETURNING id
            """),
            {
                "filename": file.filename or "unnamed.pdf",
                "page_count": len(pages),
            },
        )

        document_id = result.scalar_one()

        # Upload the original PDF to S3.
        s3_key = upload_pdf_to_s3(
            file_content=contents,
            document_id=document_id,
            filename=safe_filename,
        )

        # Save the S3 object key.
        connection.execute(
            text("""
                UPDATE documents
                SET s3_key = :s3_key
                WHERE id = :document_id
            """),
            {
                "s3_key": s3_key,
                "document_id": document_id,
            },
        )

        # Save task candidates.
        for task in task_candidates:
            connection.execute(
                text("""
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
                    VALUES (
                        :task_id,
                        :document_id,
                        :suggested_text,
                        :source_quote,
                        :page,
                        :status,
                        :method,
                        :category,
                        :due_date,
                        :confidence,
                        :needs_review,
                        :completed
                    )
                """),
                {
                    "task_id": task["task_id"],
                    "document_id": document_id,
                    "suggested_text": task["suggested_text"],
                    "source_quote": task["source_quote"],
                    "page": task["page"],
                    "status": task["status"],
                    "method": task["method"],
                    "category": task["category"],
                    "due_date": task["due_date"],
                    "confidence": task["confidence"],
                    "needs_review": int(task["needs_review"]),
                    "completed": int(task["completed"]),
                },
            )

        # Save searchable document chunks.
        for chunk in document_chunks:
            connection.execute(
                text("""
                    INSERT INTO document_chunks (
                        document_id,
                        page,
                        chunk_index,
                        content
                    )
                    VALUES (
                        :document_id,
                        :page,
                        :chunk_index,
                        :content
                    )
                """),
                {
                    "document_id": document_id,
                    "page": chunk["page"],
                    "chunk_index": chunk["chunk_index"],
                    "content": chunk["content"],
                },
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
async def get_documents():
    with engine.connect() as connection:
        result = connection.execute(
            text("""
                SELECT id, filename, page_count, created_at
                FROM documents
                ORDER BY id DESC
            """)
        )

        documents = result.mappings().all()

    return [dict(document) for document in documents]


# --------------------------------------------------
# RETRIEVE SAVED TASKS
# --------------------------------------------------

@app.get("/tasks")
async def get_tasks():
    with engine.connect() as connection:
        result = connection.execute(
            text("""
                SELECT task_id, document_id, suggested_text, source_quote,
                       page, status, method, completed, category, due_date,
                       confidence, needs_review
                FROM care_tasks
                ORDER BY document_id, page, task_id
            """)
        )

        tasks = result.mappings().all()

    return [dict(task) for task in tasks]

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

    with engine.begin() as connection:
        result = connection.execute(
            text("""
                UPDATE care_tasks
                SET status = :status
                WHERE task_id = :task_id
            """),
            {
                "status": update.status,
                "task_id": task_id,
            },
        )

        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Task not found")

    return {
        "task_id": task_id,
        "status": update.status,
    }

@app.patch("/tasks/{task_id}/completion")
def update_task_completion(
    task_id: str,
    update: TaskCompletionUpdate
):
    with engine.begin() as connection:
        result = connection.execute(
            text("""
                UPDATE care_tasks
                SET completed = :completed
                WHERE task_id = :task_id
                AND status = 'confirmed'
            """),
            {
                "completed": 1 if update.completed else 0,
                "task_id": task_id,
            },
        )

        if result.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="Task not found or task is not confirmed.",
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

    with engine.connect() as connection:
        result = connection.execute(
            text("""
                SELECT
                    dc.chunk_id,
                    dc.document_id,
                    dc.page,
                    dc.chunk_index,
                    dc.content,
                    d.filename
                FROM document_chunks dc
                JOIN documents d ON dc.document_id = d.id
                WHERE (
                    :document_id IS NULL
                    OR dc.document_id = :document_id
                )
            """),
            {"document_id": document_id},
        )

        rows = result.mappings().all()

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