CareBridge — Healthcare Document Processing Demo

CareBridge is a healthcare document processing prototype built as a learning project with assistance from AI development tools. It is an ongoing project, and there are still many improvements that could be made.

Motivation:
The purpose of CareBridge is to help patients navigate the growing number of healthcare documents they may receive from different providers. This is a problem I encountered personally while navigating healthcare as a self-pay patient. Medical information can become scattered across discharge instructions, appointment summaries, referrals, and other documents. Keeping track of important instructions and knowing where to find specific information can be difficult. CareBridge explores how document processing and large language models can make this information easier to organize, review, and access.

Architecture:
CareBridge uses a full-stack architecture combining a React frontend, Python backend, cloud storage, database persistence, authentication, and LLM-powered document processing.

<img width="2040" height="1032" alt="mermaid-diagram" src="https://github.com/user-attachments/assets/413b7f3e-666e-4b89-ad95-95f431ae4148" />

Frontend:
React + TypeScript — Provides the user interface for uploading documents, reviewing extracted tasks, managing a care checklist, and asking questions.

Vite — Frontend development and build tooling.

Supabase Auth integration — Manages user authentication and provides access tokens for authenticated API requests.

Backend:

Python + FastAPI — Handles API requests, document processing, task management, and question answering.

PyMuPDF — Extracts text from uploaded PDF documents.

Groq API + GPT-OSS 120B — Processes document text to identify actionable instructions and generates answers to user questions.

Cloud Infrastructure and Persistence

AWS S3 — Stores uploaded healthcare documents in private cloud storage.

PostgreSQL (Neon) — Persists document metadata, extracted tasks, and document text chunks used for retrieval.

Supabase — Handles authentication and authorization. The backend verifies user tokens and restricts access to each user's documents and associated data.

Render — Hosts the FastAPI backend.

Vercel — Hosts the React frontend.

Retrieval-Augmented Generation (RAG)

CareBridge includes a document-grounded question-answering pipeline.

Text is extracted from uploaded PDF documents.

The extracted text is divided into smaller chunks.

BM25 keyword retrieval identifies passages relevant to a user's question.

Retrieved passages are provided to the LLM as context.

The LLM generates an answer using the retrieved document information.

Supporting passages and page references are returned alongside the answer.

The goal is to make answers traceable to the original documents rather than relying exclusively on the model's general knowledge.

Features

1. Document Upload and Processing

Upload PDF healthcare documents.

Extract text from uploaded documents.

Store documents in private AWS S3 storage.

Persist document metadata in PostgreSQL.

<img width="1484" height="757" alt="dashboard" src="https://github.com/user-attachments/assets/ddbb13c4-130f-4b39-81dd-823c9eec87fe" />

2. AI-Powered Task Extraction

Use GPT-OSS 120B to identify potentially actionable instructions in healthcare documents.

Extract information such as follow-up appointments, referrals, and other care-related tasks.

Organize suggested tasks into categories.

Associate extracted tasks with their original source text and page number.

3. Task Review

Review AI-generated task suggestions before adding them to the care checklist.

Confirm or reject individual suggestions.

Inspect the original document passage associated with each suggestion.

<img width="1462" height="755" alt="review_tasks" src="https://github.com/user-attachments/assets/7232af58-2be2-44a7-9a1a-61e375a81edf" />

4. Care Checklist

View confirmed tasks organized by document and category.

Track task completion.

View overall checklist progress.

Keep extracted instructions accessible in one place.

<img width="1466" height="716" alt="checklist" src="https://github.com/user-attachments/assets/67e0f47e-257e-430c-8484-911b65f343d7" />

5. Document Question Answering

Select an uploaded document and ask a question about its contents.

Retrieve relevant passages using BM25.

Generate contextual answers using GPT-OSS 120B.

Display supporting passages and page references so users can verify the response against the original document.

<img width="1459" height="750" alt="rag" src="https://github.com/user-attachments/assets/2b2111a0-269a-4e01-86fc-2849bc8551f8" />

6. User Authentication and Data Isolation

<img width="574" height="670" alt="Screenshot 2026-11-08 at 10 01 55 PM" src="https://github.com/user-attachments/assets/a41a4ed5-4b11-4dd1-8c94-5dfd6b6c9aec" />

Create an account and sign in using Supabase Auth.

Verify authentication tokens on protected backend endpoints.

Scope document and task access to the authenticated user.

Delete uploaded documents and their associated application data.

How to Use

The application is deployed at:

Live Demo: https://healthcare-project-three.vercel.app

Create an account or sign in. Each user has a separate workspace.

Upload a healthcare PDF. The application extracts its text and processes it for potential care-related tasks.

Review suggested tasks. Check the extracted instructions against the original document. Confirm tasks that are relevant or reject incorrect suggestions.

Use the care checklist. Confirmed tasks appear in the checklist, where you can track their completion.

Ask questions. Select an uploaded document and ask a question about its contents. The application retrieves relevant passages and generates an answer with supporting references.

Manage your documents. View uploaded documents or delete documents you no longer need.

Local Development

Prerequisites

Python

Node.js and npm

A Supabase project

An AWS S3 bucket

A Neon PostgreSQL database

A Groq API key

Backend Setup

Navigate to the backend directory:

cd backend

Create and activate a virtual environment:

python -m venv .venv
source .venv/bin/activate

Install dependencies:

pip install -r requirements.txt

Create a .env file in the backend directory with the required configuration:

AWS_REGION=your_aws_region
S3_BUCKET_NAME=your_s3_bucket
DATABASE_URL=your_postgresql_connection_string
SUPABASE_URL=your_supabase_project_url
GROQ_API_KEY=your_groq_api_key

Start the backend:

uvicorn main:app --reload

The API will be available at http://localhost:8000.

Frontend Setup

Open another terminal and navigate to the frontend directory:

cd frontend

Install dependencies:

npm install

Create a .env file:

VITE_API_URL=http://localhost:8000
VITE_SUPABASE_URL=your_supabase_project_url
VITE_SUPABASE_ANON_KEY=your_supabase_anon_key

Start the frontend:

npm run dev

Vite will provide a local development URL in the terminal.

Limitations and Future Improvements

CareBridge is an experimental learning project, not a production healthcare application.

Some areas for future improvement include:

Improving the accuracy and consistency of LLM-based task extraction.

Supporting scanned PDFs and OCR-based document processing.

Improving retrieval quality and handling more complex questions.

Expanding document format support.

Improving error handling and user feedback.

Adding more comprehensive automated testing.

Disclaimer

This application is a prototype for educational and demonstration purposes only. It is not intended for real patient data or clinical use.

AI-generated task suggestions and answers may be incomplete or incorrect. Users should always consult their original documents and qualified healthcare professionals when interpreting medical instructions.

Do not upload real protected health information (PHI) or rely on this application for medical decisions.
