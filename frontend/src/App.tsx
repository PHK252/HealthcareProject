import { useEffect, useState } from "react";
import "./App.css";
import DocumentUpload from "./DocumentUpload";

type ApiStatus = "checking" | "online" | "offline";

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

type DocumentRecord = {
  id: number;
  filename: string;
  page_count: number;
  created_at: string;
};

type QuestionSource = {
  source: number;
  document_id: number;
  filename: string;
  page: number;
  content: string;
};

type QuestionResult = {
  answer: string;
  sources: QuestionSource[];
};

function App() {
  const [apiStatus, setApiStatus] = useState<ApiStatus>("checking");
  const [candidates, setCandidates] = useState<TaskCandidate[]>([]);
  const [documentCount, setDocumentCount] = useState(0);

  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [selectedDocumentId, setSelectedDocumentId] = useState("");
  const [question, setQuestion] = useState("");
  const [questionResult, setQuestionResult] = useState<QuestionResult | null>(null);
  const [askingQuestion, setAskingQuestion] = useState(false);
  const [questionError, setQuestionError] = useState("");

  async function refreshDocuments() {
    try {
      const response = await fetch("http://localhost:8000/documents");
      if (!response.ok) throw new Error("Could not load documents.");

      const data: DocumentRecord[] = await response.json();

      setDocuments(data);
      setDocumentCount(data.length);

      setSelectedDocumentId((current) =>
        current || (data.length > 0 ? String(data[0].id) : "")
      );
    } catch (error) {
      console.error("Document loading failed:", error);
    }
  }

  async function refreshTasks() {
    try {
      const response = await fetch("http://localhost:8000/tasks");
      if (!response.ok) throw new Error("Could not load tasks.");

      const tasks = await response.json();
      setCandidates(tasks);
    } catch (error) {
      console.error("Task loading failed:", error);
    }
  }

  useEffect(() => {
    
    fetch("http://localhost:8000/health")
      .then((response) => {
        if (!response.ok) throw new Error("API request failed");
        return response.json();
      })
      .then((data) => {
        setApiStatus(data.status === "ok" ? "online" : "offline");
      })
      .catch(() => setApiStatus("offline"));
      refreshDocuments();
      refreshTasks();
  }, []);

  const pendingCount = candidates.filter(
    (task) => task.status === "needs_review"
  ).length;

  const confirmedTasks = candidates.filter(
    (task) => task.status === "confirmed"
  );

    const categoryLabels: Record<string, string> = {
    medication: "Medications",
    appointment: "Appointments",
    follow_up: "Follow-ups",
    activity_restriction: "Activity restrictions",
    wound_care: "Wound care",
    symptom_monitoring: "Symptom monitoring",
    warning_sign: "Warning signs",
    other: "Other instructions",
  };

  const categoryOrder = [
    "medication",
    "appointment",
    "follow_up",
    "activity_restriction",
    "wound_care",
    "symptom_monitoring",
    "warning_sign",
    "other",
  ];

  const groupedTasks = categoryOrder
    .map((category) => ({
      category,
      tasks: confirmedTasks.filter(
        (task) => task.category === category
      ),
    }))
    .filter((group) => group.tasks.length > 0);

  const completedCount = confirmedTasks.filter(
    (task) => task.completed
  ).length;

  async function toggleTaskCompletion(
  taskId: string,
  completed: boolean
  ) {
    try {
      const response = await fetch(
        `http://localhost:8000/tasks/${taskId}/completion`,
        {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ completed }),
        }
      );

      if (!response.ok) {
        throw new Error("Could not update task completion.");
      }

      setCandidates((current) =>
        current.map((task) =>
          task.task_id === taskId
            ? { ...task, completed }
            : task
        )
      );
    } catch (error) {
      console.error("Completion update failed:", error);
      alert("Could not save this completion change. Please try again.");
    }
  }

  async function handleAskQuestion() {
    if (!selectedDocumentId || !question.trim()) return;

    setAskingQuestion(true);
    setQuestionError("");
    setQuestionResult(null);

    try {
      const response = await fetch(
        `http://localhost:8000/documents/${selectedDocumentId}/ask`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            question: question.trim(),
          }),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Could not answer your question.");
      }

      setQuestionResult(data);
    } catch (error) {
      setQuestionError(
        error instanceof Error
          ? error.message
          : "Could not connect to CareBridge."
      );
    } finally {
      setAskingQuestion(false);
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-icon">+</span>
          <span>CareBridge</span>
        </div>

        <p className="nav-label">YOUR HEALTH</p>
        <nav>
          <a className="nav-item active" href="#dashboard">Dashboard</a>
          <a className="nav-item" href="#documents">My documents</a>
          <a className="nav-item" href="#tasks">Care checklist</a>
        </nav>

        <div className="sidebar-footer">
          <span className={`status-dot ${apiStatus}`} />
          <span>
            API {apiStatus === "checking"
              ? "connecting..."
              : apiStatus === "online"
                ? "connected"
                : "offline"}
          </span>
        </div>
      </aside>

      <main className="main-content" id="dashboard">
        <header className="topbar">
          <span>Patient workspace</span>
          <span className="avatar">P</span>
        </header>

        <section className="welcome">
          <p className="eyebrow">YOUR CARE, ORGANIZED</p>
          <h1>Welcome to CareBridge</h1>
          <p>
            Keep your discharge instructions, follow-ups, and next steps
            in one place.
          </p>
        </section>

        <section className="stats-grid">
          <article className="stat-card">
            <span className="stat-icon">▤</span>
            <p>Documents</p>
            <h2>{documentCount}</h2>
            <span className="muted">Uploaded this session</span>
          </article>

          <article className="stat-card">
            <span className="stat-icon">✓</span>
            <p>Needs review</p>
            <h2>{pendingCount}</h2>
            <span className="muted">Suggested care tasks</span>
          </article>

          <article className="stat-card">
            <span className="stat-icon">↗</span>
            <p>Confirmed</p>
            <h2>{confirmedTasks.length}</h2>
            <span className="muted">Reviewed care tasks</span>
          </article>
        </section>

        <section className="panel" id="documents">
          <div className="section-heading">
            <div>
              <h2>Your documents</h2>
              <p>Start with your discharge paperwork.</p>
            </div>
            <span className="pill">PDF or image</span>
          </div>

          <div className="upload-area">
            <DocumentUpload
              candidates={candidates}
              onCandidatesChange={setCandidates}
              onDocumentUploaded={refreshDocuments}
            />
          </div>
        </section>

        <section className="panel" id="questions">
          <div className="section-heading">
            <div>
              <h2>Ask your documents</h2>
              <p>
                Ask questions about your uploaded discharge instructions.
              </p>
            </div>
            <span className="pill">AI assistant</span>
          </div>

          {documents.length === 0 ? (
            <div className="empty-state">
              <h3>No documents available</h3>
              <p>Upload a document before asking questions.</p>
            </div>
          ) : (
            <>
              <label htmlFor="question-document">
                Select a document
              </label>

              <select
                id="question-document"
                value={selectedDocumentId}
                onChange={(event) => {
                  setSelectedDocumentId(event.target.value);
                  setQuestionResult(null);
                  setQuestionError("");
                }}
              >
                {documents.map((document) => (
                  <option key={document.id} value={document.id}>
                    {document.filename}
                  </option>
                ))}
              </select>

              <label htmlFor="document-question">
                Your question
              </label>

              <textarea
                id="document-question"
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder="When should I schedule my follow-up appointment?"
                rows={3}
              />

              <button
                type="button"
                onClick={handleAskQuestion}
                disabled={!question.trim() || askingQuestion}
              >
                {askingQuestion ? "Searching documents..." : "Ask question"}
              </button>

              {questionError && (
                <p className="upload-error">{questionError}</p>
              )}

              {questionResult && (
                <div className="question-result">
                  <h3>Answer</h3>
                  <p className="answer-text">
                    {questionResult.answer}
                  </p>

                  <div className="answer-sources">
                    <h4>Supporting passages</h4>

                    {questionResult.sources.length === 0 ? (
                      <p>No supporting passages were retrieved.</p>
                    ) : (
                      questionResult.sources.map((source) => (
                        <details key={source.source}>
                          <summary>
                            Source {source.source} · Page {source.page}
                          </summary>
                          <blockquote>{source.content}</blockquote>
                        </details>
                      ))
                    )}
                  </div>

                  <p className="muted">
                    AI-generated response. Verify important instructions
                    against your original document and healthcare provider.
                  </p>
                </div>
              )}
            </>
          )}
        </section>

        <section className="panel" id="tasks">
          <div className="section-heading">
            <div>
              <h2>Your care checklist</h2>
              <p>Tasks you have reviewed and confirmed.</p>
            </div>
            <span className="pill">
              {confirmedTasks.length} tasks
            </span>
          </div>

          {confirmedTasks.length === 0 ? (
            <div className="empty-state">
              <div className="check-icon">✓</div>
              <h3>No confirmed tasks yet</h3>
              <p>
                Upload a document and confirm suggested tasks
                to add them to your checklist.
              </p>
            </div>
          ) : (
            <>
              <div className="checklist-progress">
                <div className="progress-label">
                  <span>Overall progress</span>
                  <strong>
                    {completedCount} of {confirmedTasks.length} completed
                  </strong>
                </div>

                <div className="progress-track">
                  <div
                    className="progress-fill"
                    style={{
                      width: `${(completedCount / confirmedTasks.length) * 100}%`,
                    }}
                  />
                </div>
              </div>

              {groupedTasks.map((group) => (
                <div className="task-category" key={group.category}>
                  <div className="category-heading">
                    <h3>
                      {categoryLabels[group.category] ?? "Other instructions"}
                    </h3>
                    <span>
                      {group.tasks.filter((task) => task.completed).length}
                      {" / "}
                      {group.tasks.length}
                    </span>
                  </div>

                  <div className="confirmed-task-list">
                    {group.tasks.map((task) => (
                      <article
                        className={`candidate-card ${task.completed ? "completed-task" : ""}`}
                        key={task.task_id}
                      >
                        <div className="candidate-heading">
                          <strong>
                            {categoryLabels[task.category] ?? "Care task"}
                          </strong>
                          <span className="task-status confirmed">
                            {task.completed ? "completed" : "pending"}
                          </span>
                        </div>

                        <p className="candidate-text">
                          {task.suggested_text}
                        </p>

                        {task.due_date && (
                          <p className="task-due-date">
                            Due: {task.due_date}
                          </p>
                        )}

                        <label className="completion-control">
                          <input
                            type="checkbox"
                            checked={task.completed}
                            onChange={(event) =>
                              toggleTaskCompletion(
                                task.task_id,
                                event.target.checked
                              )
                            }
                          />
                          Mark as completed
                        </label>

                        <details className="task-source">
                          <summary>
                            View original document · Page {task.page}
                          </summary>
                          <blockquote>{task.source_quote}</blockquote>
                        </details>
                      </article>
                    ))}
                  </div>
                </div>
              ))}
            </>
          )}
        </section>

        <footer>
          CareBridge is a prototype, not a substitute for professional
          medical advice.
        </footer>
      </main>
    </div>
  );
}

export default App;