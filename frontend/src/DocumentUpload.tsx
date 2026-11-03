import { useState } from "react";
import "./DocumentUpload.css";
import { supabase } from "./supabase";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

type ExtractedPage = {
  page: number;
  text: string;
};

type TaskCandidate = {
  task_id: string;
  document_id: number;
  suggested_text: string;
  source_quote: string;
  page: number;
  status: "needs_review" | "confirmed" | "rejected";
  method: string;
  completed: boolean;

  // Structured LLM extraction fields
  category: string;
  due_date: string | null;
  confidence: number;
  needs_review: boolean;
};

type ExtractionResult = {
  filename: string;
  page_count: number;
  pages: ExtractedPage[];
  text: string;
  task_candidates: TaskCandidate[];
  extraction_method: string;
  extraction_warning: string | null;
};

type DocumentUploadProps = {
  candidates: TaskCandidate[];
  onCandidatesChange: (candidates: TaskCandidate[]) => void;
  onDocumentUploaded: () => void;
};


export default function DocumentUpload({candidates, onCandidatesChange, onDocumentUploaded,}: DocumentUploadProps) {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<ExtractionResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [showText, setShowText] = useState(false);
  const [error, setError] = useState("");

  async function handleUpload() {
    if (!file) return;

    setLoading(true);
    setError("");
    setResult(null);

    try {
      const formData = new FormData();
      formData.append("file", file);

      const {
        data: { session },
      } = await supabase.auth.getSession();

      if (!session) {
        throw new Error("You must be signed in.");
      }

      const response = await fetch(
        `${API_URL}/documents/extract`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${session.access_token}`,
          },
          body: formData,
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Could not process this PDF.");
      }

      const extracted = data as ExtractionResult;

      setResult(extracted);

    // Retrieve ALL saved tasks, including those from earlier uploads.
      const tasksResponse = await fetch(`${API_URL}/tasks`, {
        headers: {
          Authorization: `Bearer ${session.access_token}`,
        },
      });

      if (!tasksResponse.ok) {
         throw new Error("Document uploaded, but could not reload saved tasks.");
      }

      const savedTasks = await tasksResponse.json();
      onCandidatesChange(savedTasks);

      onDocumentUploaded();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Could not connect to the CareBridge API."
      );
    } finally {
      setLoading(false);
    }
  }

  async function updateCandidate(
  taskId: string,
  status: TaskCandidate["status"]
    ) {
    try {
        const {
          data: { session },
        } = await supabase.auth.getSession();

        if (!session) {
          throw new Error("You must be signed in.");
        }

        const response = await fetch(
          `${API_URL}/tasks/${taskId}`,
          {
            method: "PATCH",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${session.access_token}`,
            },
            body: JSON.stringify({ status }),
          }
        );

        if (!response.ok) {
        throw new Error("Could not save task status.");
        }

        // Only update the interface after the backend confirms success.
        onCandidatesChange(
        candidates.map((candidate) =>
            candidate.task_id === taskId
            ? { ...candidate, status }
            : candidate
        )
        );

        setError("");
    } catch (err) {
        setError(
        err instanceof Error
            ? err.message
            : "Could not save task status."
        );
    }
    }

  const confirmedCount = candidates.filter(
    (candidate) => candidate.status === "confirmed"
  ).length;

  const pendingCount = candidates.filter(
    (candidate) => candidate.status === "needs_review"
  ).length;

  const rejectedCount = candidates.filter(
    (candidate) => candidate.status === "rejected"
  ).length;

  return (
    <section className="document-upload">
      <h2>Upload discharge instructions</h2>
      <p>
        Extract document text and review possible care tasks.
      </p>

      <input
        type="file"
        accept="application/pdf,.pdf"
        onChange={(event) => {
          setFile(event.target.files?.[0] ?? null);
          setResult(null);
          setError("");
        }}
      />

      <button
        type="button"
        onClick={handleUpload}
        disabled={!file || loading}
      >
        {loading ? "Extracting..." : "Upload and extract"}
      </button>

      {error && <p className="upload-error">{error}</p>}

      {result && (
      <>
        <div className="extraction-result">
          <h3>{result.filename}</h3>
          <p>Extracted {result.page_count} page(s).</p>

          <p>
            Extraction method:{" "}
            <strong>
              {result.extraction_method === "ollama_llama3.2"
                ? "Local LLM (Llama 3.2)"
                : "Rule-based fallback"}
            </strong>
          </p>

          {result.extraction_warning && (
            <p className="upload-error">{result.extraction_warning}</p>
          )}

          <button
            type="button"
            className="secondary-button"
            onClick={() => setShowText((current) => !current)}
          >
            {showText ? "Hide extracted text" : "View extracted text"}
          </button>

          {showText &&
            result.pages.map((page) => (
              <div key={page.page} className="extracted-page">
                <h4>Page {page.page}</h4>
                <pre>
                  {page.text || "(No selectable text on this page.)"}
                </pre>
              </div>
            ))}
        </div>

        <div className="task-review">
          <h3>Care task review</h3>
          <p>
            These are AI-generated suggestions, not verified medical
            instructions. Review each item against the original document.
          </p>

          <div className="review-counts">
            <span>Needs review: {pendingCount}</span>
            <span>Confirmed: {confirmedCount}</span>
            <span>Rejected: {rejectedCount}</span>
          </div>

          {candidates.length === 0 ? (
            <p>No candidate tasks were found in this document.</p>
          ) : (
            candidates.map((candidate) => (
              <article className="candidate-card" key={candidate.task_id}>
                <div className="candidate-heading">
                  <strong>
                    {candidate.category.replaceAll("_", " ")}
                  </strong>

                  <span className={`task-status ${candidate.status}`}>
                    {candidate.status.replace("_", " ")}
                  </span>
                </div>

                <p className="candidate-text">
                  {candidate.suggested_text}
                </p>

                <div className="candidate-metadata">
                  <span>
                    <strong>Category:</strong>{" "}
                    {candidate.category.replaceAll("_", " ")}
                  </span>

                  <span>
                    <strong>Due date:</strong>{" "}
                    {candidate.due_date ?? "Not specified"}
                  </span>

                  <span>
                    <strong>Extraction score:</strong>{" "}
                    {candidate.confidence.toFixed(2)}
                  </span>

                  <span>
                    <strong>Method:</strong> {candidate.method}
                  </span>
                </div>

                <div className="source-evidence">
                  <strong>Source · Page {candidate.page}</strong>
                  <blockquote>{candidate.source_quote}</blockquote>
                </div>

                <div className="candidate-actions">
                  <button
                    type="button"
                    onClick={() =>
                      updateCandidate(candidate.task_id, "confirmed")
                    }
                    disabled={candidate.status === "confirmed"}
                  >
                    Confirm
                  </button>

                  <button
                    type="button"
                    className="reject-button"
                    onClick={() =>
                      updateCandidate(candidate.task_id, "rejected")
                    }
                    disabled={candidate.status === "rejected"}
                  >
                    Reject
                  </button>

                  {candidate.status !== "needs_review" && (
                    <button
                      type="button"
                      className="secondary-button"
                      onClick={() =>
                        updateCandidate(candidate.task_id, "needs_review")
                      }
                    >
                      Undo
                    </button>
                  )}
                </div>
              </article>
            ))
          )}
        </div>
      </>
    )}
    </section>
  );
}