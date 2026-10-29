import { useState } from "react";
import "./DocumentUpload.css";

type ExtractedPage = {
  page: number;
  text: string;
};

type TaskCandidate = {
  task_id: string;
  suggested_text: string;
  source_quote: string;
  page: number;
  status: "needs_review" | "confirmed" | "rejected";
  method: string;
};

type ExtractionResult = {
  filename: string;
  page_count: number;
  pages: ExtractedPage[];
  text: string;
  task_candidates: TaskCandidate[];
};

export default function DocumentUpload() {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<ExtractionResult | null>(null);
  const [candidates, setCandidates] = useState<TaskCandidate[]>([]);
  const [loading, setLoading] = useState(false);
  const [showText, setShowText] = useState(false);
  const [error, setError] = useState("");

  async function handleUpload() {
    if (!file) return;

    setLoading(true);
    setError("");
    setResult(null);
    setCandidates([]);

    try {
      const formData = new FormData();
      formData.append("file", file);

      const response = await fetch(
        "http://localhost:8000/documents/extract",
        {
          method: "POST",
          body: formData,
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Could not process this PDF.");
      }

      const extracted = data as ExtractionResult;

      setResult(extracted);
      setCandidates(extracted.task_candidates ?? []);
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

  function updateCandidate(
    taskId: string,
    status: TaskCandidate["status"]
  ) {
    setCandidates((current) =>
      current.map((candidate) =>
        candidate.task_id === taskId
          ? { ...candidate, status }
          : candidate
      )
    );
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
          setCandidates([]);
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
              These are rule-based suggestions, not verified medical
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
                <article
                  className="candidate-card"
                  key={candidate.task_id}
                >
                  <div className="candidate-heading">
                    <strong>{candidate.task_id}</strong>
                    <span className={`task-status ${candidate.status}`}>
                      {candidate.status.replace("_", " ")}
                    </span>
                  </div>

                  <p className="candidate-text">
                    {candidate.suggested_text}
                  </p>

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