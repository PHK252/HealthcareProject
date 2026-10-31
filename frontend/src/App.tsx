import { useEffect, useState } from "react";
import "./App.css";
import DocumentUpload from "./DocumentUpload";

type ApiStatus = "checking" | "online" | "offline";

type TaskCandidate = {
  task_id: string;
  suggested_text: string;
  source_quote: string;
  page: number;
  status: "needs_review" | "confirmed" | "rejected";
  method: string;
  completed: boolean;
};

function App() {
  const [apiStatus, setApiStatus] = useState<ApiStatus>("checking");
  const [candidates, setCandidates] = useState<TaskCandidate[]>([]);
  const [documentCount, setDocumentCount] = useState(0);

  async function refreshDocuments() {
    try {
      const response = await fetch("http://localhost:8000/documents");
      if (!response.ok) throw new Error("Could not load documents.");

      const documents = await response.json();
      setDocumentCount(documents.length);
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
            <div className="confirmed-task-list">
              {confirmedTasks.map((task) => (
                <article className="candidate-card" key={task.task_id}>
                  <div className="candidate-heading">
                    <strong>{task.task_id}</strong>
                    <span className="task-status confirmed">confirmed</span>
                  </div>
                  <p className="candidate-text">{task.suggested_text}</p>
                  <label className="completion-control">
                    <input
                      type="checkbox"
                      checked={task.completed}
                      onChange={(event) =>
                        toggleTaskCompletion(task.task_id, event.target.checked)
                      }
                    />
                    Mark as completed
                  </label>
                  <div className="source-evidence">
                    <strong>Original document · Page {task.page}</strong>
                    <blockquote>{task.source_quote}</blockquote>
                  </div>
                </article>
              ))}
            </div>
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