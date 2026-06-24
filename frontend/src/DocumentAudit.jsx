import { useState } from "react"
import { runDocumentAudit, fetchFiles } from "./api"
import { Search, Folder, FileText, ClipboardCheck, Lightbulb, AlertTriangle, CheckCircle, Ban, ListChecks } from "lucide-react"

const ALL_DEPARTMENTS = [
  "Engineering", "Security", "HR", "AI",
  "Customer_Support", "Operations",
]

const SEVERITY_COLORS = {
  high: "#dc2626",
  medium: "#f59e0b",
  low: "#3b82f6",
  none: "#10b981",
}

export default function DocumentAudit() {
  const [selected, setSelected] = useState(["Engineering", "Security"])
  const [loading, setLoading] = useState(false)
  const [report, setReport] = useState(null)
  const [error, setError] = useState(null)
  const [elapsed, setElapsed] = useState(null)
  const [auditedFiles, setAuditedFiles] = useState(null)
  const [expandedDept, setExpandedDept] = useState(null)

  const toggleDept = (dept) => {
    setSelected((prev) =>
      prev.includes(dept)
        ? prev.filter((d) => d !== dept)
        : [...prev, dept]
    )
  }

  const handleRun = async () => {
    if (selected.length < 2) {
      setError("Select at least 2 departments to compare.")
      return
    }

    setLoading(true)
    setError(null)
    setReport(null)
    setAuditedFiles(null)
    setExpandedDept(null)

    const t0 = performance.now()
    try {
      const result = await runDocumentAudit({ departments: selected })
      setReport(result)
      setElapsed(((performance.now() - t0) / 1000).toFixed(1))

      // Fetch all indexed files, grouped by department
      const allFiles = await fetchFiles()
      const deptFiles = {}
      for (const f of allFiles) {
        if (f.indexed && selected.includes(f.category)) {
          if (!deptFiles[f.category]) deptFiles[f.category] = []
          deptFiles[f.category].push(f)
        }
      }
      setAuditedFiles(deptFiles)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="audit-dashboard">
      <div className="audit-header">
        <h2><Search size={22} /> Cross-Department Document Audit</h2>
        <p>
          Compare documents across departments to find contradictions,
          outdated references, and policy misalignments.
        </p>
      </div>

      <div className="audit-content">
        {/* Control panel */}
        <div className="audit-controls">
          <div className="audit-card">
            <h3>Select Departments</h3>
            <div className="dept-grid">
              {ALL_DEPARTMENTS.map((d) => (
                <button
                  key={d}
                  className={`dept-chip ${selected.includes(d) ? "active" : ""}`}
                  onClick={() => toggleDept(d)}
                  disabled={loading}
                >
                  {d.replace("_", " ")}
                  {selected.includes(d) && <span className="check">✓</span>}
                </button>
              ))}
            </div>

            <button
              className="btn btn-audit"
              onClick={handleRun}
              disabled={loading || selected.length < 2}
            >
              {loading ? "Auditing..." : "Run Audit"}
            </button>

            {elapsed && !loading && (
              <div className="audit-elapsed">
                Completed in {elapsed}s
              </div>
            )}
          </div>

          {/* Audited departments card — always visible */}
          <div className="audit-card audit-docs-card">
            <h3><Folder size={14} /> Documents Audited</h3>
            {!report ? (
              <div className="audit-docs-empty">No audited documents yet</div>
            ) : (
              <div className="audit-docs-list">
                {selected.map((d) => {
                  const files = auditedFiles?.[d] || []
                  const isOpen = expandedDept === d
                  return (
                    <div key={d}>
                      <button
                        className={`audit-doc-item ${isOpen ? "open" : ""}`}
                        onClick={() => setExpandedDept(isOpen ? null : d)}
                      >
                        <span className="audit-doc-icon">{isOpen ? <Folder size={14} /> : <FileText size={14} />}</span>
                        <span className="audit-doc-name">{d.replace("_", " ")}</span>
                        <span className="audit-doc-count">{files.length} doc{files.length !== 1 ? "s" : ""}</span>
                        <span className={`arrow ${isOpen ? "open" : ""}`}>▾</span>
                      </button>
                      {isOpen && (
                        <div className="audit-doc-files">
                          {files.length === 0 ? (
                            <div className="audit-doc-empty">No indexed documents</div>
                          ) : (
                            files.map((f) => (
                              <div key={f.path} className="audit-doc-file">
                                <span className="audit-doc-file-icon"><FileText size={12} /></span>
                                <span className="audit-doc-file-name" title={f.name}>{f.name}</span>
                              </div>
                            ))
                          )}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          {/* Suggestions card — always visible */}
          <div className="audit-card audit-suggestions-card">
            <h3><Lightbulb size={14} /> Suggestions &amp; Actions</h3>
            {!report || !report.suggestions || report.suggestions.length === 0 ? (
              <div className="audit-docs-empty">No suggestions yet</div>
            ) : (
              <>
                <div className="suggestions-list">
                  {report.suggestions.map((s, i) => (
                    <div key={i} className="suggestion-item">
                      <span className="suggestion-topic">{s.topic}</span>
                      <p className="suggestion-action">{s.action}</p>
                      {s.involved_depts && (
                        <div className="suggestion-depts">
                          {s.involved_depts.map((d) => (
                            <span key={d} className="suggestion-dept-tag">{d}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
                {report.steps && report.steps.length > 0 && (
                  <>
                    <h3 className="steps-heading"><ListChecks size={14} /> Recommended Steps</h3>
                    <ol className="steps-list">
                      {report.steps.map((step, i) => (
                        <li key={i} className="step-item">{step}</li>
                      ))}
                    </ol>
                  </>
                )}
              </>
            )}
          </div>

          {error && (
            <div className="audit-error">
              <strong>Error:</strong> {error}
            </div>
          )}
        </div>

        {/* Report */}
        <div className="audit-report">
          {loading && (
            <div className="audit-loading">
              <div className="audit-spinner" />
              <div>
                <strong>Auditing documents across {selected.length} departments...</strong>
                <p>Checking 9 topics for contradictions. This may take 30-60s.</p>
              </div>
            </div>
          )}

          {!report && !loading && !error && (
            <div className="audit-empty">
              <div className="audit-empty-icon"><ClipboardCheck /></div>
              <h3>No audit run yet</h3>
              <p>Select departments and click "Run Audit" to find document contradictions.</p>
            </div>
          )}

          {report && (
            <div className="audit-results">
              {/* Summary bar */}
              <div className="audit-summary">
                <div className="summary-stat conflict">
                  <span className="stat-num">{report.conflicts.length}</span>
                  <span className="stat-label">Conflicts</span>
                </div>
                <div className="summary-stat clean">
                  <span className="stat-num">{report.clean.length}</span>
                  <span className="stat-label">Clean</span>
                </div>
                <div className="summary-stat nodocs">
                  <span className="stat-num">{report.no_docs.length}</span>
                  <span className="stat-label">No Overlap</span>
                </div>
                <div className="summary-stat total">
                  <span className="stat-num">{report.topics_checked}</span>
                  <span className="stat-label">Total Topics</span>
                </div>
              </div>

              <p className="audit-summary-text">{report.summary}</p>

              {/* Conflict cards */}
              {report.conflicts.length > 0 && (
                <div className="audit-section">
                  <h3 className="audit-section-title conflict-title">
                    <AlertTriangle size={14} /> Conflicts Found ({report.conflicts.length})
                  </h3>
                  {report.conflicts.map((c, i) => (
                    <ConflictCard key={i} finding={c} />
                  ))}
                </div>
              )}

              {/* Clean topics */}
              {report.clean.length > 0 && (
                <div className="audit-section">
                  <h3 className="audit-section-title clean-title">
                    <CheckCircle size={14} /> No Contradictions ({report.clean.length})
                  </h3>
                  <div className="clean-chips">
                    {report.clean.map((t, i) => (
                      <span key={i} className="clean-chip">{t}</span>
                    ))}
                  </div>
                </div>
              )}

              {/* No docs */}
              {report.no_docs.length > 0 && (
                <div className="audit-section">
                  <h3 className="audit-section-title nodocs-title">
                    <Ban size={14} /> No Cross-Dept Coverage ({report.no_docs.length})
                  </h3>
                  <div className="clean-chips">
                    {report.no_docs.map((t, i) => (
                      <span key={i} className="nodocs-chip">{t}</span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function ConflictCard({ finding }) {
  const [expanded, setExpanded] = useState(false)
  const sev = SEVERITY_COLORS[finding.severity] || "#6b7280"

  return (
    <div className="conflict-card">
      <div className="conflict-header" onClick={() => setExpanded(!expanded)}>
        <div className="conflict-topic-row">
          <span className="severity-dot" style={{ background: sev }} />
          <strong>{finding.topic}</strong>
          <span className="severity-badge" style={{ background: sev }}>
            {finding.severity}
          </span>
        </div>
        <span className={`expand-arrow ${expanded ? "open" : ""}`}>▾</span>
      </div>

      <p className="conflict-summary">{finding.finding}</p>

      {expanded && (
        <div className="conflict-details">
          <div className="conflict-quotes">
            <div className="quote-block">
              <div className="quote-label">
                <FileText size={13} /> {finding.dept_a_doc || "Document A"}
              </div>
              <div className="quote-text">
                "{finding.dept_a_quote || "No excerpt available"}"
              </div>
            </div>
            <div className="quote-vs">vs</div>
            <div className="quote-block">
              <div className="quote-label">
                <FileText size={13} /> {finding.dept_b_doc || "Document B"}
              </div>
              <div className="quote-text">
                "{finding.dept_b_quote || "No excerpt available"}"
              </div>
            </div>
          </div>
          {finding.depts_compared && (
            <div className="conflict-meta">
              Departments compared: {finding.depts_compared.join(", ")}
            </div>
          )}
        </div>
      )}
    </div>
  )
}