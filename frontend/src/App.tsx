import { useEffect, useState } from "react";
import "./App.css";
import DocumentUpload from "./DocumentUpload";
import { supabase } from "./supabase";


async function apiFetch(
  url: string,
  options: RequestInit = {}
) {
  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (!session) {
    throw new Error("You must be signed in.");
  }

  const headers = new Headers(options.headers);

  headers.set(
    "Authorization",
    `Bearer ${session.access_token}`
  );

  return fetch(url, {
    ...options,
    headers,
  });
}

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

  const [session, setSession] = useState<any>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authMode, setAuthMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [authError, setAuthError] = useState("");
  const [authMessage, setAuthMessage] = useState("");

  async function refreshDocuments() {
    try {
      const response = await apiFetch("http://localhost:8000/documents");
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
      const response = await apiFetch("http://localhost:8000/tasks");
      if (!response.ok) throw new Error("Could not load tasks.");

      const tasks = await response.json();
      setCandidates(tasks);
    } catch (error) {
      console.error("Task loading failed:", error);
    }
  }

  useEffect(() => {
  supabase.auth.getSession().then(({ data }) => {
    setSession(data.session);
    setAuthLoading(false);
  });

  const {
    data: { subscription },
  } = supabase.auth.onAuthStateChange((_event, session) => {
    setSession(session);
    setAuthLoading(false);
  });

  return () => subscription.unsubscribe();
  }, []);

  useEffect(() => {
    if (!session) return;

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
  }, [session]);

  const pendingCount = candidates.filter(
    (task) => task.status === "needs_review"
  ).length;

  const selectedDocumentTasks = candidates.filter(
  (task) => task.document_id === Number(selectedDocumentId)
  );

  const confirmedTasks = candidates.filter(
  (task) => task.status === "confirmed"
  );
  
  const tasksNeedingReview = selectedDocumentTasks.filter(
  (task) => task.status === "needs_review"
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

  const checklistByDocument = documents
    .map((document) => {
      const documentTasks = confirmedTasks.filter(
        (task) => task.document_id === document.id
      );

      return {
        document,
        groupedTasks: categoryOrder
          .map((category) => ({
            category,
            tasks: documentTasks.filter(
              (task) => task.category === category
            ),
          }))
          .filter((group) => group.tasks.length > 0),
      };
    })
    .filter((group) => group.groupedTasks.length > 0);

  const completedCount = confirmedTasks.filter(
    (task) => task.completed
  ).length;

  async function reviewTask(
    taskId: string,
    status: "confirmed" | "rejected"
  ) {
    try {
      const response = await apiFetch(
        `http://localhost:8000/tasks/${taskId}`,
        {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ status }),
        }
      );

      if (!response.ok) {
        throw new Error("Could not update task status.");
      }

      setCandidates((current) =>
        current.map((task) =>
          task.task_id === taskId
            ? { ...task, status }
            : task
        )
      );
    } catch (error) {
      console.error("Task review failed:", error);
      alert("Could not update this task. Please try again.");
    }
  }


  async function toggleTaskCompletion(
  taskId: string,
  completed: boolean
  ) {
    try {
      const response = await apiFetch(
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
      const response = await apiFetch(
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

  async function handleDeleteDocument(documentId: number) {
    const documentToDelete = documents.find(
      (document) => document.id === documentId
    );

    if (!documentToDelete) return;

    const confirmed = window.confirm(
      `Are you sure you want to delete "${documentToDelete.filename}"? This will also delete its associated care tasks.`
    );

    if (!confirmed) return;

    try {
      const response = await apiFetch(
        `http://localhost:8000/documents/${documentId}`,
        { method: "DELETE" }
      );

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Failed to delete document.");
      }

      // If this was the selected document, switch to another one.
      if (selectedDocumentId === String(documentId)) {
        const remainingDocuments = documents.filter(
          (document) => document.id !== documentId
        );

        setSelectedDocumentId(
          remainingDocuments.length > 0
            ? String(remainingDocuments[0].id)
            : ""
        );

        setQuestionResult(null);
        setQuestionError("");
      }

      await refreshDocuments();
      await refreshTasks();
    } catch (error) {
      console.error("Document deletion failed:", error);
      window.alert(
        error instanceof Error ? error.message : "Failed to delete document."
      );
    }
  }


  async function handleAuthSubmit(event: React.FormEvent) {
    event.preventDefault();
    setAuthError("");
    setAuthMessage("");

    const { error } =
      authMode === "signup"
        ? await supabase.auth.signUp({ email, password })
        : await supabase.auth.signInWithPassword({ email, password });

    if (error) {
      setAuthError(error.message);
      return;
    }

    if (authMode === "signup") {
      setAuthMessage("Account created. Check your email if confirmation is required.");
    }
  }

  async function handleSignOut() {
    const { error } = await supabase.auth.signOut();

    if (error) {
      setAuthError(error.message);
    }
  }

  if (authLoading) {
    return <div className="auth-screen">Loading CareBridge...</div>;
  }

  if (!session) {
    return (
      <div className="auth-screen">
        <form className="auth-card" onSubmit={handleAuthSubmit}>
          <h1>CareBridge</h1>
          <p>Your care, organized.</p>

          <h2>{authMode === "signin" ? "Welcome back" : "Create your account"}</h2>

          <label htmlFor="auth-email">Email</label>
          <input
            id="auth-email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />

          <label htmlFor="auth-password">Password</label>
          <input
            id="auth-password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
            minLength={6}
          />

          {authError && <p className="upload-error">{authError}</p>}
          {authMessage && <p>{authMessage}</p>}

          <button type="submit">
            {authMode === "signin" ? "Sign in" : "Create account"}
          </button>

          <button
            type="button"
            className="auth-switch"
            onClick={() => {
              setAuthMode(authMode === "signin" ? "signup" : "signin");
              setAuthError("");
              setAuthMessage("");
            }}
          >
            {authMode === "signin"
              ? "Need an account? Sign up"
              : "Already have an account? Sign in"}
          </button>
        </form>
      </div>
    );
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
          <button type="button" onClick={handleSignOut}>
            Sign out
          </button>
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

          <div className="document-list">
            <h3>Uploaded documents</h3>

            {documents.length === 0 ? (
              <p className="muted">No documents uploaded yet.</p>
            ) : (
              documents.map((document) => (
                <article className="document-card" key={document.id}>
                  <div>
                    <strong>{document.filename}</strong>
                    <p className="muted">
                      {document.page_count} pages · Uploaded{" "}
                      {new Date(document.created_at).toLocaleDateString()}
                    </p>
                  </div>

                  <button
                    type="button"
                    className="delete-button"
                    onClick={() => handleDeleteDocument(document.id)}
                  >
                    Delete
                  </button>
                </article>
              ))
            )}
          </div>
        </section>

        <section className="panel" id="review">
          <div className="section-heading">
            <div>
              <h2>Review suggested tasks</h2>
              <p>
                Check each suggested instruction against your original document.
              </p>
            </div>
            <span className="pill">
              {tasksNeedingReview.length} awaiting review
            </span>
          </div>

          {tasksNeedingReview.length === 0 ? (
            <div className="empty-state">
              <h3>All caught up!</h3>
              <p>No tasks are waiting for review.</p>
            </div>
          ) : (
            tasksNeedingReview.map((task) => (
              <article className="candidate-card" key={task.task_id}>
                <div className="candidate-heading">
                  <strong>
                    {categoryLabels[task.category] ?? "Other instructions"}
                  </strong>
                  <span className="task-status">
                    Needs review
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

                <details className="task-source">
                  <summary>
                    View original document · Page {task.page}
                  </summary>
                  <blockquote>{task.source_quote}</blockquote>
                </details>

                <div className="review-actions">
                  <button
                    type="button"
                    onClick={() => reviewTask(task.task_id, "confirmed")}
                  >
                    Confirm task
                  </button>

                  <button
                    type="button"
                    className="delete-button"
                    onClick={() => reviewTask(task.task_id, "rejected")}
                  >
                    Reject
                  </button>
                </div>
              </article>
            ))
          )}
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
                    width: `${
                      confirmedTasks.length > 0
                        ? (completedCount / confirmedTasks.length) * 100
                        : 0
                    }%`,
                  }}
                />
              </div>
            </div>

            {checklistByDocument.map(({ document, groupedTasks }) => (
              <div className="document-task-group" key={document.id}>
                <h3 className="document-task-heading">
                  {document.filename}
                </h3>

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
                              checked={Boolean(task.completed)}
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