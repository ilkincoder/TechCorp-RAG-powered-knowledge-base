import { useState, useRef, useEffect } from "react"
import { generateOnboardingPlanStream, generateOnboardingN8nStream } from "./api"
import { Target, ClipboardList, Paperclip } from "lucide-react"

// "fastapi" = direct SSE streaming with templates (1-2s, uses Few-Shot + CoT)
// "n8n"     = n8n workflow (30s+, for MCP proof-of-concept)
const ONBOARDING_MODE = "fastapi"

const DEPARTMENTS = ["Engineering", "HR", "Security", "IT", "Product", "Design", "Marketing", "Operations"]

const ROLES_BY_DEPT = {
  Engineering: ["Junior Backend Engineer", "Senior Backend Engineer", "Frontend Developer", "DevOps Engineer", "Data Engineer", "QA Engineer"],
  HR: ["HR Coordinator", "Recruiter", "HR Business Partner", "Payroll Specialist"],
  Security: ["Security Analyst", "Security Engineer", "Compliance Officer"],
  IT: ["IT Support Specialist", "System Administrator", "Network Engineer"],
  Product: ["Junior Product Manager", "Senior Product Manager", "Product Owner"],
  Design: ["UX Designer", "UI Designer", "Product Designer"],
  Marketing: ["Marketing Coordinator", "Content Strategist", "SEO Specialist"],
  Operations: ["Operations Analyst", "Project Manager", "Business Analyst"],
}

const EXPERIENCE_LEVELS = [
  { label: "Entry-level (0-1 year)", value: "Entry-level" },
  { label: "Junior (1-3 years)", value: "1-3 years" },
  { label: "Mid-level (3-5 years)", value: "3-5 years" },
  { label: "Senior (5-8 years)", value: "5-8 years" },
  { label: "Lead (8+ years)", value: "8+ years" },
]

export default function OnboardingDashboard() {
  const [form, setForm] = useState({
    role: "",
    department: "",
    experience: "",
  })
  const [customDept, setCustomDept] = useState("")
  const [customRole, setCustomRole] = useState("")
  const [plan, setPlan] = useState("")
  const [sources, setSources] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [done, setDone] = useState(false)
  const scrollRef = useRef(null)

  const roles = ROLES_BY_DEPT[form.department] || []

  // The effective values used for generation (custom overrides dropdown)
  const effectiveDept = form.department === "__other__" ? customDept : form.department
  const effectiveRole = form.role === "__other__" ? customRole : form.role

  // Auto-scroll during streaming
  useEffect(() => {
    if (loading && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [plan, loading])

  const handleChange = (field) => (e) => {
    const value = e.target.value
    setForm((prev) => {
      const next = { ...prev, [field]: value }
      if (field === "department") {
        next.role = ROLES_BY_DEPT[value]?.[0] || (value === "__other__" ? "__other__" : "")
        if (value !== "__other__") setCustomDept("")
      }
      if (field === "role" && value !== "__other__") {
        setCustomRole("")
      }
      return next
    })
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    const role = effectiveRole
    const department = effectiveDept
    if (!role || !department || !form.experience) return

    setLoading(true)
    setError(null)
    setPlan("")
    setSources(null)
    setDone(false)

    const profile = {
      role: role,
      department: department,
      experience: form.experience,
    }

    if (ONBOARDING_MODE === "fastapi") {
      // Real SSE streaming — tokens appear ~1-2s after submit
      generateOnboardingPlanStream({
        ...profile,
        onToken: (token) => {
          setPlan((prev) => prev + token)
        },
        onDone: (srcs, fullPlan) => {
          setSources(srcs)
          setDone(true)
          setLoading(false)
        },
        onError: (errMsg) => {
          setError(errMsg)
          setLoading(false)
        },
      })
      return
    }

    // n8n-powered streaming — n8n retrieves, FastAPI streams tokens
    generateOnboardingN8nStream({
      ...profile,
      onToken: (token) => {
        setPlan((prev) => prev + token)
      },
      onDone: (srcs, fullPlan) => {
        setDone(true)
        setLoading(false)
      },
      onError: (errMsg) => {
        setError(errMsg)
        setLoading(false)
      },
    })
  }

  return (
    <div className="onboarding-dashboard">
      <div className="ob-header">
        <h2><Target size={22} /> Onboarding Plan Generator</h2>
        <p>Enter the new hire's details to generate a personalized 4-week training plan.</p>
      </div>

      <div className="ob-content">
        {/* Form panel */}
        <div className="ob-form-panel">
          <form onSubmit={handleSubmit} className="ob-form">
            <div className="form-field">
              <label htmlFor="department">Department</label>
              <select id="department" value={form.department} onChange={handleChange("department")}>
                <option value="">-- Select department --</option>
                {DEPARTMENTS.map((d) => (
                  <option key={d} value={d}>{d}</option>
                ))}
                <option value="__other__">Other (specify)...</option>
              </select>
              {form.department === "__other__" && (
                <input
                  type="text"
                  className="form-custom-input"
                  placeholder="Enter department name..."
                  value={customDept}
                  onChange={(e) => setCustomDept(e.target.value)}
                />
              )}
            </div>

            <div className="form-field">
              <label htmlFor="role">Role</label>
              <select id="role" value={form.role} onChange={handleChange("role")}>
                <option value="">-- Select role --</option>
                {roles.map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
                <option value="__other__">Other (specify)...</option>
              </select>
              {form.role === "__other__" && (
                <input
                  type="text"
                  className="form-custom-input"
                  placeholder="Enter role title..."
                  value={customRole}
                  onChange={(e) => setCustomRole(e.target.value)}
                />
              )}
            </div>

            <div className="form-field">
              <label htmlFor="experience">Experience Level</label>
              <select id="experience" value={form.experience} onChange={handleChange("experience")}>
                <option value="">-- Select experience --</option>
                {EXPERIENCE_LEVELS.map((l) => (
                  <option key={l.value} value={l.value}>{l.label}</option>
                ))}
              </select>
            </div>

            <button
              type="submit"
              className="btn btn-generate"
              disabled={loading || !effectiveRole || !effectiveDept || !form.experience}
            >
              {loading ? "Generating..." : "Generate Plan"}
            </button>
          </form>

          <div className="ob-form-preview">
            <h4>Profile Preview</h4>
            <div className="preview-card">
              <div className="preview-row">
                <span className="preview-label">Role</span>
                <span className="preview-value">{effectiveRole || "—"}</span>
              </div>
              <div className="preview-row">
                <span className="preview-label">Department</span>
                <span className="preview-value">{effectiveDept || "—"}</span>
              </div>
              <div className="preview-row">
                <span className="preview-label">Experience</span>
                <span className="preview-value">{form.experience || "—"}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Result panel */}
        <div className="ob-result-panel" ref={scrollRef}>
          {error && (
            <div className="ob-error">
              <strong>Error:</strong> {error}
              <p className="ob-error-hint">
                Make sure the backend is running and Qdrant has indexed documents.
              </p>
            </div>
          )}

          {!plan && !loading && !error && (
            <div className="ob-empty">
              <div className="ob-empty-icon"><ClipboardList /></div>
              <h3>No plan generated yet</h3>
              <p>Fill in the new hire's profile and click "Generate Plan".</p>
            </div>
          )}

          {loading && !plan && (
            <div className="ob-loading">
              <div className="ob-loading-spinner" />
              <div>
                <strong>Generating onboarding plan...</strong>
                <p>Retrieving documents and building a personalized 4-week plan.</p>
              </div>
            </div>
          )}

          {/* Streaming plan display */}
          {plan && (
            <div className="plan-article">
              <PlanContent text={plan} isStreaming={loading} />
              {done && <SourceFooter sources={sources} />}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Markdown → Clean HTML ──────────────────────────────────────────
function PlanContent({ text, isStreaming }) {
  const blocks = parseMarkdown(text)
  const firstHrIdx = blocks.findIndex(b => b.type === "hr")

  return (
    <div className={`plan-rendered ${isStreaming ? "streaming" : ""}`}>
      {blocks.map((block, i) => {
        const isIntro = firstHrIdx !== -1 && i < firstHrIdx && block.type === "para"
        if (block.type === "h1") return <h3 key={i} className="plan-h1">{block.text}</h3>
        if (block.type === "h2") return <h4 key={i} className="plan-h2">{block.text}</h4>
        if (block.type === "h3") return <h5 key={i} className="plan-h3">{block.text}</h5>
        if (block.type === "hr") return <hr key={i} className="plan-hr" />
        if (block.type === "bullet") return <li key={i} className="plan-li">{renderInline(block.text)}</li>
        if (block.type === "bullet-list") return <ul key={i} className="plan-ul">{block.items.map((item, j) => <li key={j} className="plan-li">{renderInline(item)}</li>)}</ul>
        if (block.type === "week-header") return <div key={i} className="plan-week-header">{renderInline(block.text)}</div>
        if (block.type === "para") return <p key={i} className={isIntro ? "plan-intro" : "plan-para"}>{renderInline(block.text)}</p>
        if (block.type === "empty") return <br key={i} />
        return <p key={i} className="plan-para">{renderInline(block.text)}</p>
      })}
      {isStreaming && <span className="stream-cursor">▊</span>}
    </div>
  )
}

function SourceFooter({ sources }) {
  if (!sources || sources.length === 0) return null
  return (
    <div className="plan-sources-footer">
      <h4><Paperclip size={14} /> Sources ({sources.length})</h4>
      <div className="plan-sources-grid">
        {sources.map((s, i) => {
          const filename = s.source.split("/").pop()
          return (
            <a
              key={i}
              className="plan-source-chip"
              href={`/api/files/view/${encodeURIComponent(filename)}`}
              target="_blank"
              rel="noopener noreferrer"
              title={`Open ${filename}`}
            >
              <span className="plan-source-cat">{s.category}</span>
              <span className="plan-source-file">{filename}</span>
            </a>
          )
        })}
      </div>
    </div>
  )
}

// ── Inline renderer: **bold** etc ──────────────────────────────────
function renderInline(text) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={i}>{part.slice(2, -2)}</strong>
    }
    return part
  })
}

// ── Markdown Parser ────────────────────────────────────────────────
function parseMarkdown(raw) {
  const lines = raw.split("\n")
  const blocks = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]
    const trimmed = line.trim()

    // Empty line
    if (!trimmed) {
      if (blocks.length > 0 && blocks[blocks.length - 1].type !== "empty") {
        blocks.push({ type: "empty" })
      }
      i++
      continue
    }

    // Horizontal rule
    if (/^---+$/.test(trimmed)) {
      blocks.push({ type: "hr" })
      i++
      continue
    }

    // Week header: Week 1 — ... or Week 1: ...
    const weekMatch = trimmed.match(/^\*{0,2}(Week\s+\d+[\s—:\-–].+?)\*{0,2}\s*$/)
    if (weekMatch) {
      blocks.push({ type: "week-header", text: weekMatch[1].replace(/\*+$/, "").trim() })
      i++
      continue
    }

    // H1 heading: # ...
    if (/^#\s/.test(trimmed)) {
      blocks.push({ type: "h1", text: trimmed.replace(/^#\s*/, "").replace(/\*+/g, "").trim() })
      i++
      continue
    }

    // H2 heading: ## ...
    if (/^##\s/.test(trimmed)) {
      blocks.push({ type: "h2", text: trimmed.replace(/^##\s*/, "").replace(/\*+/g, "").trim() })
      i++
      continue
    }

    // H3 heading: ### ...
    if (/^###\s/.test(trimmed)) {
      blocks.push({ type: "h3", text: trimmed.replace(/^###\s*/, "").replace(/\*+/g, "").trim() })
      i++
      continue
    }

    // Bold-only line (acts as mini-header): **Text**
    if (/^\*\*[^*]+\*\*$/.test(trimmed)) {
      blocks.push({ type: "h3", text: trimmed.replace(/\*\*/g, "").trim() })
      i++
      continue
    }

    // Bullet list — collect consecutive bullet items
    if (/^[-*•]\s/.test(trimmed)) {
      const items = []
      while (i < lines.length && /^[-*•]\s/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^[-*•]\s+/, ""))
        i++
      }
      blocks.push({ type: "bullet-list", items })
      continue
    }

    // Numbered list item (Day 1-2: ...)
    const numberedMatch = trimmed.match(/^\d+[.)]\s+(.+)/)
    if (numberedMatch) {
      blocks.push({ type: "bullet", text: trimmed })
      i++
      continue
    }

    // Paragraph — text block (may span multiple lines)
    let para = trimmed
    i++
    while (i < lines.length && lines[i].trim() && !isSpecialLine(lines[i])) {
      para += " " + lines[i].trim()
      i++
    }
    blocks.push({ type: "para", text: para })
  }

  return blocks
}

function isSpecialLine(line) {
  const t = line.trim()
  return (
    /^#{1,3}\s/.test(t) ||
    /^[-*•]\s/.test(t) ||
    /^---+$/.test(t) ||
    /^\*{0,2}Week\s+\d/.test(t) ||
    /^\*\*[^*]+\*\*$/.test(t) ||
    /^\d+[.)]\s/.test(t) ||
    !t
  )
}