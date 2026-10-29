import { useEffect, useState } from "react";
import "./App.css";
import DocumentUpload from "./DocumentUpload";

type ApiStatus = "checking" | "online" | "offline";

function App() {
  const [apiStatus, setApiStatus] = useState<ApiStatus>("checking");

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
  }, []);

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
            <h2>0</h2>
            <span className="muted">Uploaded so far</span>
          </article>
          <article className="stat-card">
            <span className="stat-icon">✓</span>
            <p>Care tasks</p>
            <h2>0</h2>
            <span className="muted">Ready for review</span>
          </article>
          <article className="stat-card">
            <span className="stat-icon">↗</span>
            <p>Completed</p>
            <h2>0</h2>
            <span className="muted">Tasks checked off</span>
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
            <DocumentUpload />
          </div>
        </section>

        <section className="panel" id="tasks">
          <div className="section-heading">
            <div>
              <h2>Your care checklist</h2>
              <p>Reviewed tasks will appear here.</p>
            </div>
            <span className="pill">0 tasks</span>
          </div>

          <div className="empty-state">
            <div className="check-icon">✓</div>
            <h3>No tasks yet</h3>
            <p>
              Once you upload and review a document, your confirmed
              next steps will appear here.
            </p>
          </div>
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