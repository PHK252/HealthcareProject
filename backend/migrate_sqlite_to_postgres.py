import os
import sqlite3
from pathlib import Path
from datetime import datetime

from sqlalchemy import text


# Explicitly target the local PostgreSQL database.
os.environ["DATABASE_URL"] = "postgresql+psycopg://localhost/carebridge"

# Import the existing database setup from the FastAPI application.
from main import engine, initialize_database


BASE_DIR = Path(__file__).resolve().parent
SQLITE_PATH = BASE_DIR / "carebridge.db"


def migrate():
    print("Initializing PostgreSQL schema...")
    initialize_database()

    # Read the existing SQLite records.
    source = sqlite3.connect(SQLITE_PATH)
    source.row_factory = sqlite3.Row

    try:
        documents = [dict(row) for row in source.execute(
            "SELECT * FROM documents ORDER BY id"
        )]
        tasks = [dict(row) for row in source.execute(
            "SELECT * FROM care_tasks ORDER BY task_id"
        )]
        chunks = [dict(row) for row in source.execute(
            "SELECT * FROM document_chunks ORDER BY chunk_id"
        )]
    finally:
        source.close()

    print(f"SQLite records: {len(documents)} documents, "
          f"{len(tasks)} tasks, {len(chunks)} chunks")

    # Convert SQLite timestamp strings to Python datetime objects.
    for document in documents:
        value = document["created_at"]
        if isinstance(value, str):
            document["created_at"] = datetime.fromisoformat(value)

    # Insert all records in one transaction.
    with engine.begin() as connection:

        # Avoid accidentally duplicating existing PostgreSQL data.
        existing = connection.execute(text("""
            SELECT
                (SELECT COUNT(*) FROM documents) +
                (SELECT COUNT(*) FROM care_tasks) +
                (SELECT COUNT(*) FROM document_chunks)
        """)).scalar_one()

        if existing != 0:
            raise RuntimeError(
                "PostgreSQL tables are not empty. "
                "Migration stopped to avoid duplicate records."
            )

        # 1. Documents first (parent records).
        for document in documents:
            connection.execute(text("""
                INSERT INTO documents
                    (id, filename, page_count, created_at, s3_key)
                VALUES
                    (:id, :filename, :page_count, :created_at, :s3_key)
            """), document)

        # 2. Care tasks (reference documents).
        for task in tasks:
            connection.execute(text("""
                INSERT INTO care_tasks
                    (task_id, document_id, suggested_text, source_quote,
                     page, status, method, completed, category, due_date,
                     confidence, needs_review)
                VALUES
                    (:task_id, :document_id, :suggested_text, :source_quote,
                     :page, :status, :method, :completed, :category, :due_date,
                     :confidence, :needs_review)
            """), task)

        # 3. Document chunks (reference documents).
        for chunk in chunks:
            connection.execute(text("""
                INSERT INTO document_chunks
                    (chunk_id, document_id, page, chunk_index, content)
                VALUES
                    (:chunk_id, :document_id, :page, :chunk_index, :content)
            """), chunk)

        # Reset auto-generated ID sequences to avoid future collisions.
        connection.execute(text("""
            SELECT setval(
                pg_get_serial_sequence('documents', 'id'),
                COALESCE((SELECT MAX(id) FROM documents), 1),
                EXISTS(SELECT 1 FROM documents)
            )
        """))

        connection.execute(text("""
            SELECT setval(
                pg_get_serial_sequence('document_chunks', 'chunk_id'),
                COALESCE((SELECT MAX(chunk_id) FROM document_chunks), 1),
                EXISTS(SELECT 1 FROM document_chunks)
            )
        """))

    print("\nMigration completed successfully!")
    print(f"Documents: {len(documents)}")
    print(f"Care tasks: {len(tasks)}")
    print(f"Document chunks: {len(chunks)}")


if __name__ == "__main__":
    migrate()