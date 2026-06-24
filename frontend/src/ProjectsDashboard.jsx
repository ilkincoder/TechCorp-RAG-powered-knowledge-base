import { useState, useEffect } from "react"
import { fetchGapRequests, approveGapRequest, confirmGapRequest, deleteGapRequest } from "./api"
import { ClipboardList, FileEdit, CheckCircle, Clock, FileText } from "lucide-react"

export default function ProjectsDashboard({ visible, refreshKey = 0 }) {
  const [activeTab, setActiveTab] = useState("pending")
  const [requests, setRequests] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [approvingId, setApprovingId] = useState(null)
  const [confirmingId, setConfirmingId] = useState(null)
  const [deletingId, setDeletingId] = useState(null)

  const loadRequests = () => {
    setLoading(true)
    setError(null)
    fetchGapRequests()
      .then((data) => { setRequests(data); setLoading(false) })
      .catch((err) => { setError(err.message); setLoading(false) })
  }

  useEffect(() => { if (visible) loadRequests() }, [visible, refreshKey])

  const handleApprove = async (gapId) => {
    setApprovingId(gapId)
    try {
      await approveGapRequest(gapId)
      loadRequests()
    } catch (err) {
      setError(err.message)
    } finally {
      setApprovingId(null)
    }
  }

  const handleConfirm = async (gapId) => {
    setConfirmingId(gapId)
    try {
      await confirmGapRequest(gapId)
      loadRequests()
    } catch (err) {
      setError(err.message)
    } finally {
      setConfirmingId(null)
    }
  }

  const handleDelete = async (gapId) => {
    if (!confirm("Delete this request? This cannot be undone.")) return
    setDeletingId(gapId)
    try {
      await deleteGapRequest(gapId)
      loadRequests()
    } catch (err) {
      setError(err.message)
    } finally {
      setDeletingId(null)
    }
  }

  const pending = requests.filter((r) => r.status === "pending")
  const drafts = requests.filter((r) => r.status === "draft_ready")
  const approved = requests.filter((r) => r.status === "approved")

  const formatDate = (iso) => {
    if (!iso) return ""
    return new Date(iso).toLocaleDateString("en-US", {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    })
  }

  /* ── Loading ─────────────────────────── */
  if (loading) {
    return (
      <div className="requests-page">
        <div className="requests-header">
          <h2><ClipboardList size={22} /> Requests & Approvals</h2>
          <p>Track knowledge-gap requests and approve new content for the knowledge base.</p>
        </div>
        <div className="loading-state">Loading requests…</div>
      </div>
    )
  }

  /* ── Error ───────────────────────────── */
  if (error) {
    return (
      <div className="requests-page">
        <div className="requests-header">
          <h2><ClipboardList size={22} /> Requests & Approvals</h2>
          <p>Track knowledge-gap requests and approve new content for the knowledge base.</p>
        </div>
        <div className="error-state">
          <p>Failed to load requests: {error}</p>
          <button onClick={loadRequests}>Retry</button>
        </div>
      </div>
    )
  }

  /* ── Main ────────────────────────────── */
  return (
    <div className="requests-page">
      {/* Header */}
      <div className="requests-header">
        <h2><ClipboardList size={22} /> Requests & Approvals</h2>
        <p>Track knowledge-gap requests and approve new content for the knowledge base.</p>
      </div>

      {/* Tabs */}
      <div className="requests-tabs">
        <button
          className={`requests-tab ${activeTab === "pending" ? "active" : ""}`}
          onClick={() => setActiveTab("pending")}
        >
          <Clock size={15} />
          <span>Pending Requests</span>
          {pending.length > 0 && (
            <span className="requests-badge">{pending.length}</span>
          )}
        </button>
        <button
          className={`requests-tab ${activeTab === "drafts" ? "active" : ""}`}
          onClick={() => setActiveTab("drafts")}
        >
          <FileEdit size={15} />
          <span>Drafts</span>
          {drafts.length > 0 && (
            <span className="requests-badge">{drafts.length}</span>
          )}
        </button>
        <button
          className={`requests-tab ${activeTab === "approved" ? "active" : ""}`}
          onClick={() => setActiveTab("approved")}
        >
          <CheckCircle size={15} />
          <span>Approved Requests</span>
        </button>
      </div>

      {/* Pending Tab */}
      {activeTab === "pending" && (
        <div className="requests-list">
          {pending.length === 0 && (
            <div className="empty-state">No pending requests. Knowledge gaps will appear here when users submit them.</div>
          )}
          {pending.map((req) => (
            <div key={req.id} className="request-card">
              <div className="request-card-body">
                <div className="request-card-top">
                  <span className="request-status pending"><Clock size={12} /> Pending</span>
                  <span className="request-dept">{req.suggested_department.replace(/_/g, " ")}</span>
                </div>
                <div className="request-query">"{req.query}"</div>
                {req.message && (
                  <div className="request-message">{req.message}</div>
                )}
                <div className="request-meta">
                  <span>By {req.requester_name || "Anonymous"}</span>
                  <span>·</span>
                  <span>{formatDate(req.created_at)}</span>
                </div>
              </div>
              <div className="request-card-actions">
                <button
                  className="btn-approve"
                  onClick={() => handleApprove(req.id)}
                  disabled={approvingId === req.id}
                >
                  {approvingId === req.id ? "Generating…" : "✓ Generate Draft"}
                </button>
                <button
                  className="btn-reject"
                  onClick={() => handleDelete(req.id)}
                  disabled={deletingId === req.id}
                  title="Delete"
                >
                  ✕
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Drafts Tab */}
      {activeTab === "drafts" && (
        <div className="requests-list">
          {drafts.length === 0 && (
            <div className="empty-state">No drafts ready for review. Generate a draft from a pending request to see it here.</div>
          )}
          {drafts.map((req) => (
            <div key={req.id} className="request-card draft-ready">
              <div className="request-card-body">
                <div className="request-card-top">
                  <span className="request-status draft"><FileEdit size={12} /> Draft Ready</span>
                  <span className="request-dept">{req.suggested_department.replace(/_/g, " ")}</span>
                </div>
                <div className="request-query">"{req.query}"</div>
                {req.message && (
                  <div className="request-message">{req.message}</div>
                )}
                {req.draft_content && (
                  <details className="draft-preview">
                    <summary className="draft-preview-summary">
                      <FileText size={12} /> Preview draft ({req.draft_content.length.toLocaleString()} chars)
                    </summary>
                    <div className="draft-preview-content">
                      <pre className="draft-markdown">{req.draft_content}</pre>
                    </div>
                  </details>
                )}
                <div className="request-meta">
                  <span>By {req.requester_name || "Anonymous"}</span>
                  <span>·</span>
                  <span>Draft generated {formatDate(req.draft_generated_at)}</span>
                </div>
              </div>
              <div className="request-card-actions">
                <button
                  className="btn-confirm"
                  onClick={() => handleConfirm(req.id)}
                  disabled={confirmingId === req.id}
                >
                  {confirmingId === req.id ? "Confirming…" : "✓ Confirm & Index"}
                </button>
                <button
                  className="btn-reject"
                  onClick={() => handleDelete(req.id)}
                  disabled={deletingId === req.id}
                  title="Delete draft"
                >
                  ✕
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Approved Tab */}
      {activeTab === "approved" && (
        <div className="requests-list">
          {approved.length === 0 && (
            <div className="empty-state">No approved requests yet. Approved requests will appear here as a permanent history.</div>
          )}
          {approved.map((req) => (
            <div key={req.id} className="request-card approved">
              <div className="request-card-body">
                <div className="request-card-top">
                  <span className="request-status approved"><CheckCircle size={12} /> Approved</span>
                  <span className="request-dept">{req.suggested_department.replace(/_/g, " ")}</span>
                </div>
                <div className="request-query">"{req.query}"</div>
                {req.message && (
                  <div className="request-message">{req.message}</div>
                )}
                <div className="request-meta">
                  <span>By {req.requester_name || "Anonymous"}</span>
                  <span>·</span>
                  <span>Approved {formatDate(req.approved_at)}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}