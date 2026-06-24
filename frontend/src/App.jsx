import { useState, useRef, useEffect } from "react"
import { chatMessageSmartStream, healthCheck, fetchFiles, uploadFile, fetchDepartments, formatFileSize, submitGapRequest, fetchGapRequests } from "./api"
import OnboardingDashboard from "./OnboardingDashboard"
import DocumentAudit from "./DocumentAudit"
import ProjectsDashboard from "./ProjectsDashboard"
import EvalDashboard from "./EvalDashboard"
import {
  LayoutDashboard,
  ClipboardList,
  Target,
  ShieldCheck,
  Users,
  ChevronDown,
  ChevronUp,
  ChevronRight,
  Search,
  Settings,
  LogOut,
  Folder,
  FileText,
  CloudUpload,
  LayoutGrid,
  List,
  RefreshCw,
  Plus,
  MapPin,
  Briefcase,
  BarChart3,
} from "lucide-react"

function generateSessionId() {
  return `sess_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

const NAV_ITEMS = [
  { key: "home",       label: "Home",                  icon: <LayoutDashboard /> },
  { key: "requests",   label: "Requests & Approvals",  icon: <ClipboardList /> },
  { key: "onboarding", label: "Onboarding",            icon: <Target /> },
  { key: "audit",      label: "Audit",                 icon: <ShieldCheck /> },
  { key: "eval",       label: "Evaluations",          icon: <BarChart3 /> },
  { key: "team",       label: "Team",                  icon: <Users /> },
]

const DEPARTMENTS = [
  "AI",
  "Customer Support",
  "Engineering",
  "HR",
  "Operations",
  "Security",
]

// Map display names (used in sidebar) to filesystem category names
const DEPT_TO_CATEGORY = {
  "AI": "AI",
  "Customer Support": "Customer_Support",
  "Engineering": "Engineering",
  "HR": "HR",
  "Operations": "Operations",
  "Security": "Security",
}

const IDEA_QUESTIONS = [
  "Have a question about deployment?",
  "What is the incident escalation process?",
  "How does disaster recovery work?",
  "Need help with production access?",
  "Ask anything about TechCorp policies",
]

// Wrapper styles: propagate flex layout from main-panel, or hide entirely
const hiddenStyle = { display: "none" }
const viewStyle = { flex: 1, display: "flex", flexDirection: "column", minHeight: 0, overflow: "hidden" }
const homeStyle = { flex: 1, display: "flex", flexDirection: "column", minHeight: 0, overflow: "hidden" }
const teamStyle = { flex: 1, display: "flex", flexDirection: "column", minHeight: 0, overflow: "hidden" }

export default function App() {
  const [view, setView] = useState("home")
  const [chatOpen, setChatOpen] = useState(false)
  const [chatWidth, setChatWidth] = useState(420)
  const resizeRef = useRef({ startX: 0, startW: 0 })
  const [currentQuestion, setCurrentQuestion] = useState(0)
  const [ideaVisible, setIdeaVisible] = useState(false)
  const fadeTimeoutRef = useRef(null)

  // Sidebar state
  const [pendingCount, setPendingCount] = useState(0)
  const [departmentsOpen, setDepartmentsOpen] = useState(true)
  const [expandedDepts, setExpandedDepts] = useState({})
  const [selectedDept, setSelectedDept] = useState(null)  // department whose Overview is active
  const [gapRefreshKey, setGapRefreshKey] = useState(0)   // bump to refresh ProjectsDashboard
  const [profileMenuOpen, setProfileMenuOpen] = useState(false)
  const profileRef = useRef(null)

  // Fetch pending gap-request count for nav badge
  useEffect(() => {
    fetchGapRequests().then((data) => {
      const pending = data.filter((r) => r.status === "pending")
      setPendingCount(pending.length)
    }).catch(() => {})
  }, [])

  // Close profile popover on outside click
  useEffect(() => {
    const handleClick = (e) => {
      if (profileRef.current && !profileRef.current.contains(e.target)) {
        setProfileMenuOpen(false)
      }
    }
    if (profileMenuOpen) {
      document.addEventListener("mousedown", handleClick)
    }
    return () => document.removeEventListener("mousedown", handleClick)
  }, [profileMenuOpen])

  const toggleDepartment = (dept) => {
    setExpandedDepts((prev) => ({ ...prev, [dept]: !prev[dept] }))
  }

  const handleResizeStart = (e) => {
    e.preventDefault()
    resizeRef.current = { startX: e.clientX, startW: chatWidth }
    document.addEventListener("mousemove", handleResizeMove)
    document.addEventListener("mouseup", handleResizeEnd)
    document.body.style.cursor = "ew-resize"
    document.body.style.userSelect = "none"
  }

  const handleResizeMove = (e) => {
    const dx = resizeRef.current.startX - e.clientX
    const newW = Math.min(700, Math.max(320, resizeRef.current.startW + dx))
    setChatWidth(newW)
  }

  const handleResizeEnd = () => {
    document.removeEventListener("mousemove", handleResizeMove)
    document.removeEventListener("mouseup", handleResizeEnd)
    document.body.style.cursor = ""
    document.body.style.userSelect = ""
  }

  // Rotating idea-label questions next to the floating chat button
  useEffect(() => {
    if (chatOpen) return

    const initTimer = setTimeout(() => setIdeaVisible(true), 200)

    const interval = setInterval(() => {
      setIdeaVisible(false)
      fadeTimeoutRef.current = setTimeout(() => {
        setCurrentQuestion((prev) => (prev + 1) % IDEA_QUESTIONS.length)
        setIdeaVisible(true)
      }, 300)
    }, 3500)

    return () => {
      clearTimeout(initTimer)
      clearInterval(interval)
      if (fadeTimeoutRef.current) {
        clearTimeout(fadeTimeoutRef.current)
        fadeTimeoutRef.current = null
      }
    }
  }, [chatOpen])

  return (
    <>
      <div className="layout" style={chatOpen ? { marginRight: chatWidth } : {}}>
        {/* ══════ Column 1: Left Sidebar ══════ */}
        <aside className="sidebar">

          {/* ── Header: Workspace Switcher + Search ── */}
          <div className="sidebar-header">
            <button className="workspace-switcher" title="Switch workspace">
              <span>TechCorp</span>
              <ChevronDown />
            </button>
            <button
              className="search-trigger"
              title="Search (⌘K)"
              onClick={() => setChatOpen(true)}
            >
              <Search />
            </button>
          </div>

          {/* ── Scrollable Body ── */}
          <div className="sidebar-body">

            {/* Primary nav */}
            <div className="sidebar-section">
              <div className="sidebar-label">Workspace</div>
              <nav className="sidebar-nav">
                {NAV_ITEMS.map((item) => (
                  <button
                    key={item.key}
                    className={`btn-nav ${view === item.key ? "active" : ""}`}
                    onClick={() => setView(item.key)}
                  >
                    <span className="nav-icon">{item.icon}</span>
                    <span>{item.label}</span>
                    {item.key === "requests" && pendingCount > 0 && (
                      <span className="nav-badge">{pendingCount}</span>
                    )}
                  </button>
                ))}
              </nav>
            </div>

            {/* Departments tree */}
            <div className="sidebar-section">
              <div
                className="sidebar-label-row"
                onClick={() => setDepartmentsOpen((v) => !v)}
              >
                <span>Departments</span>
                <ChevronRight className={departmentsOpen ? "open" : ""} />
              </div>
              {departmentsOpen && (
                <div className="projects-tree">
                  {DEPARTMENTS.map((dept) => (
                    <div className="tree-folder" key={dept}>
                      <div
                        className="tree-folder-header"
                        onClick={() => toggleDepartment(dept)}
                      >
                        <span className={`tree-chevron ${expandedDepts[dept] ? "open" : ""}`}>
                          <ChevronRight />
                        </span>
                        <Folder size={13} />
                        <span>{dept}</span>
                      </div>
                      {expandedDepts[dept] && (
                        <div className="tree-children">
                          <div
                            className={`tree-child ${selectedDept === dept ? "active" : ""}`}
                            onClick={(e) => {
                              e.stopPropagation()
                              setSelectedDept(dept)
                              setView("department")
                            }}
                          >
                            <FileText size={12} />
                            <span>Overview</span>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* ── Footer: User Profile ── */}
          <button
            className="sidebar-footer-profile"
            onClick={() => setProfileMenuOpen((v) => !v)}
            ref={profileRef}
          >
            <div className="sb-avatar">IH</div>
            <div className="sb-profile-info">
              <div className="sb-profile-name">Ilkin Hamzayev</div>
              <div className="sb-profile-role">Administrator</div>
            </div>
            <span className={`sb-chevron ${profileMenuOpen ? "open" : ""}`}>
              <ChevronUp />
            </span>

            {profileMenuOpen && (
              <div className="profile-popover">
                <button className="profile-popover-item"
                  onClick={(e) => { e.stopPropagation(); /* settings placeholder */ }}>
                  <Settings />
                  <span>Settings</span>
                </button>
                <button className="profile-popover-item"
                  onClick={(e) => { e.stopPropagation(); /* logout placeholder */ }}>
                  <LogOut />
                  <span>Log out</span>
                </button>
              </div>
            )}
          </button>
        </aside>

      {/* ══════ Column 2: Middle Panel ══════ */}
      <main className="main-panel">
        <div style={view === "home" ? homeStyle : hiddenStyle}><HomeView /></div>
        <div style={view === "department" ? viewStyle : hiddenStyle}><DepartmentFilesView dept={selectedDept} category={DEPT_TO_CATEGORY[selectedDept]} visible={view === "department"} /></div>
        <div style={view === "requests" ? viewStyle : hiddenStyle}><ProjectsDashboard visible={view === "requests"} refreshKey={gapRefreshKey} /></div>
        <div style={view === "team" ? teamStyle : hiddenStyle}><TeamView onNavigate={setView} /></div>
        <div style={view === "onboarding" ? viewStyle : hiddenStyle}><OnboardingDashboard /></div>
        <div style={view === "audit" ? viewStyle : hiddenStyle}><DocumentAudit /></div>
        <div style={view === "eval" ? viewStyle : hiddenStyle}><EvalDashboard /></div>
      </main>

    </div>

    {/* ══════ Floating Chat Widget ══════ */}
    {chatOpen ? (
      <aside className="chat-overlay" style={{ width: chatWidth }}>
        <div className="chat-resize-handle" onMouseDown={handleResizeStart} />
        <ChatPanel onMinimize={() => setChatOpen(false)} onGapSubmitted={() => setGapRefreshKey(k => k + 1)} />
      </aside>
    ) : (
      <div className="chat-float-container">
        <div className="chat-idea-label">
          <span className={`chat-idea-text${ideaVisible ? " visible" : ""}`}>
            {IDEA_QUESTIONS[currentQuestion]}
          </span>
        </div>
        <button
          className="chat-float-btn"
          onClick={() => setChatOpen(true)}
          title="Open AI Assistant"
        >
          <span className="chat-float-icon">🤖</span>
          <span className="chat-float-pulse" />
        </button>
      </div>
    )}
    </>
  )
}

/* ── Department Files View ────────────────────────────────────── */
function DepartmentFilesView({ dept, category, visible }) {
  const [files, setFiles] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [viewMode, setViewMode] = useState("list")

  useEffect(() => {
    if (!visible) return
    setLoading(true)
    setError(null)
    fetchFiles()
      .then((data) => {
        const filtered = data.filter((f) => f.category === category)
        setFiles(filtered)
        setLoading(false)
      })
      .catch((err) => { setError(err.message); setLoading(false) })
  }, [category, visible])

  if (loading) {
    return (
      <div className="dept-files-view">
        <div className="dept-files-header">
          <div className="breadcrumbs">
            <span>Departments</span>
            <span className="breadcrumb-sep">›</span>
            <span className="breadcrumb-active">{dept}</span>
          </div>
        </div>
        <div className="loading-state">Loading documents…</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="dept-files-view">
        <div className="dept-files-header">
          <div className="breadcrumbs">
            <span>Departments</span>
            <span className="breadcrumb-sep">›</span>
            <span className="breadcrumb-active">{dept}</span>
          </div>
        </div>
        <div className="error-state">
          <p>Failed to load documents: {error}</p>
          <button onClick={() => window.location.reload()}>Retry</button>
        </div>
      </div>
    )
  }

  return (
    <div className="dept-files-view">
      <div className="dept-files-header">
        <div className="breadcrumbs">
          <span>Departments</span>
          <span className="breadcrumb-sep">›</span>
          <span className="breadcrumb-active">{dept}</span>
        </div>
        <div className="controls-actions">
          <button
            className={`btn-icon${viewMode === "grid" ? " active" : ""}`}
            onClick={() => setViewMode("grid")}
            title="Grid view"
          >
            <LayoutGrid size={16} />
          </button>
          <button
            className={`btn-icon${viewMode === "list" ? " active" : ""}`}
            onClick={() => setViewMode("list")}
            title="List view"
          >
            <List size={16} />
          </button>
        </div>
      </div>

      {files.length === 0 && (
        <div className="empty-state">
          No documents found in {dept} department.
        </div>
      )}

      {/* Grid View */}
      {files.length > 0 && viewMode === "grid" && (
        <div className="file-grid">
          {files.map((f) => (
            <div key={f.path} className="file-card">
              <div className="file-card-icon">
                <span className="file-icon pdf">PDF</span>
              </div>
              <a
                className="file-card-name"
                href={`/api/files/view/${encodeURIComponent(f.name)}`}
                target="_blank"
                rel="noopener noreferrer"
                title={f.name}
              >
                {f.name}
              </a>
              <div className="file-card-meta">
                <span className={`status-badge ${f.indexed ? "indexed" : "not-indexed"}`}>
                  {f.indexed ? "Indexed" : "Not Indexed"}
                </span>
                <span className="category-chip">{f.category}</span>
              </div>
              <div className="file-card-footer">
                <span>{f.added}</span>
                <span>·</span>
                <span>{formatFileSize(f.size)}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* List / Table View */}
      {files.length > 0 && viewMode === "list" && (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>File Name</th>
                <th>Status</th>
                <th>Category</th>
                <th>Added</th>
                <th>Size</th>
              </tr>
            </thead>
            <tbody>
              {files.map((f) => (
                <tr key={f.path}>
                  <td>
                    <div className="file-cell">
                      <span className="file-icon pdf">PDF</span>
                      <div>
                        <a
                          className="file-name file-name-link"
                          href={`/api/files/view/${encodeURIComponent(f.name)}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          title={`Open ${f.name} in new tab`}
                        >
                          {f.name}
                        </a>
                      </div>
                    </div>
                  </td>
                  <td>
                    <span className={`status-badge ${f.indexed ? "indexed" : "not-indexed"}`}>
                      {f.indexed ? "Indexed" : "Not Indexed"}
                    </span>
                  </td>
                  <td>
                    <span className="category-chip">{f.category}</span>
                  </td>
                  <td style={{ color: "var(--text-secondary)", fontSize: "0.82rem" }}>{f.added}</td>
                  <td style={{ color: "var(--text-tertiary)", fontSize: "0.82rem" }}>{formatFileSize(f.size)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/* ── Home View (Knowledge Management) ─────────────────────────── */
function HomeView() {
  const [files, setFiles] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Upload state
  const [departments, setDepartments] = useState([])
  const [selectedFile, setSelectedFile] = useState(null)
  const [selectedDept, setSelectedDept] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState(null)
  const [showModal, setShowModal] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef(null)

  // View & sort state
  const [viewMode, setViewMode] = useState("list")   // 'list' | 'grid'
  const [sortBy, setSortBy] = useState("newest")      // 'newest' | 'category' | 'name' | 'size'

  /* ── Load files + departments ─────────────────────────────────── */
  const loadFiles = () => {
    setLoading(true)
    setError(null)
    fetchFiles()
      .then((data) => { setFiles(data); setLoading(false) })
      .catch((err) => { setError(err.message); setLoading(false) })
  }

  useEffect(() => {
    loadFiles()
    fetchDepartments()
      .then(setDepartments)
      .catch(() => setDepartments([]))
  }, [])

  /* ── Sorted files ──────────────────────────────────────────────── */
  const sortedFiles = [...files].sort((a, b) => {
    switch (sortBy) {
      case "newest":
        return b.added.localeCompare(a.added)  // newest first
      case "category":
        return a.category.localeCompare(b.category) || b.added.localeCompare(a.added)
      case "name":
        return a.name.localeCompare(b.name)
      case "size":
        return b.size - a.size  // largest first
      default:
        return 0
    }
  })

  /* ── Open file picker ─────────────────────────────────────────── */
  const openFilePicker = () => {
    fileInputRef.current?.click()
  }

  /* ── File selected via input ──────────────────────────────────── */
  const handleFilePicked = (e) => {
    const file = e.target.files?.[0]
    if (file) {
      setSelectedFile(file)
      setSelectedDept(null)
      setUploadError(null)
      setShowModal(true)
    }
    // Reset so picking the same file again triggers onChange
    e.target.value = ""
  }

  /* ── Drag-and-drop handlers ───────────────────────────────────── */
  const handleDragOver = (e) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(true)
  }

  const handleDragLeave = (e) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(false)
  }

  const handleDrop = (e) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(false)

    const file = e.dataTransfer?.files?.[0]
    if (file) {
      setSelectedFile(file)
      setSelectedDept(null)
      setUploadError(null)
      setShowModal(true)
    }
  }

  /* ── Upload ───────────────────────────────────────────────────── */
  const handleUpload = async () => {
    if (!selectedFile || !selectedDept) return
    setUploading(true)
    setUploadError(null)

    try {
      await uploadFile(selectedFile, selectedDept)
      // Success — close modal and refresh file list
      setShowModal(false)
      setSelectedFile(null)
      setSelectedDept(null)
      loadFiles()
    } catch (err) {
      setUploadError(err.message)
    } finally {
      setUploading(false)
    }
  }

  /* ── Shared header ───────────────────────────────────────────── */
  const header = (
    <>
      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf"
        style={{ display: "none" }}
        onChange={handleFilePicked}
      />

      {/* Upload zone — click opens file picker, supports drag-and-drop */}
      <div
        className={`upload-zone${dragOver ? " drag-over" : ""}`}
        onClick={openFilePicker}
        onDragOver={handleDragOver}
        onDragEnter={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <div className="upload-icon"><CloudUpload /></div>
        <div className="upload-title">Click to upload or drag and drop</div>
        <div className="upload-sub">PDF — up to 50 MB per file</div>
      </div>

      <div className="controls-bar">
        <div className="breadcrumbs">
          <span>Home</span>
          <span className="breadcrumb-sep">›</span>
          <span className="breadcrumb-active">Knowledge Base</span>
        </div>
        <div className="controls-actions">
          <select
            className="sort-select"
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
          >
            <option value="newest">Latest Added</option>
            <option value="category">Category</option>
            <option value="name">Name</option>
            <option value="size">Size</option>
          </select>
          <button
            className={`btn-icon${viewMode === "grid" ? " active" : ""}`}
            onClick={() => setViewMode("grid")}
            title="Grid view"
          >
            <LayoutGrid size={16} />
          </button>
          <button
            className={`btn-icon${viewMode === "list" ? " active" : ""}`}
            onClick={() => setViewMode("list")}
            title="List view"
          >
            <List size={16} />
          </button>
          <button className="btn-primary" onClick={openFilePicker}>
            <Plus size={16} />
            <span>Add New</span>
          </button>
        </div>
      </div>
    </>
  )

  /* ── Loading ─────────────────────────────────────────────────── */
  if (loading) {
    return (
      <>
        {header}
        <div className="loading-state">Loading files…</div>
      </>
    )
  }

  /* ── Error ───────────────────────────────────────────────────── */
  if (error) {
    return (
      <>
        {header}
        <div className="error-state">
          <p>Failed to load files: {error}</p>
          <button onClick={loadFiles}>Retry</button>
        </div>
      </>
    )
  }

  /* ── Empty ───────────────────────────────────────────────────── */
  if (files.length === 0) {
    return (
      <>
        {header}
        <div className="empty-state">No files found in knowledge base.</div>
      </>
    )
  }

  /* ── File table ──────────────────────────────────────────────── */
  return (
    <>
      {header}

      {/* ── Department Selection Modal ────────────────────────────── */}
      {showModal && (
        <div className="modal-backdrop" onClick={() => !uploading && setShowModal(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Add Document</h3>
              <button
                className="modal-close"
                onClick={() => !uploading && setShowModal(false)}
                disabled={uploading}
              >
                ✕
              </button>
            </div>

            <div className="modal-body">
              {/* File info */}
              <div className="modal-file-info">
                <span className="modal-file-icon"><FileText size={20} /></span>
                <div>
                  <div className="modal-file-name">{selectedFile?.name}</div>
                  <div className="modal-file-size">{selectedFile ? formatFileSize(selectedFile.size) : ""}</div>
                </div>
              </div>

              {/* Department picker */}
              <div className="modal-section-label">Select Department</div>
              {departments.length === 0 && (
                <div className="modal-hint">Loading departments…</div>
              )}
              <div className="dept-chip-list">
                {departments.map((dept) => (
                  <button
                    key={dept}
                    className={`dept-chip${selectedDept === dept ? " active" : ""}`}
                    onClick={() => setSelectedDept(dept)}
                    disabled={uploading}
                  >
                    {selectedDept === dept && <span className="dept-check">✓</span>}
                    {dept}
                  </button>
                ))}
              </div>

              {/* Error */}
              {uploadError && (
                <div className="modal-error">{uploadError}</div>
              )}
            </div>

            <div className="modal-footer">
              <button
                className="btn-secondary"
                onClick={() => setShowModal(false)}
                disabled={uploading}
              >
                Cancel
              </button>
              <button
                className="btn-primary"
                onClick={handleUpload}
                disabled={!selectedDept || uploading}
              >
                {uploading ? "Uploading…" : "Upload & Index"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Grid View ─────────────────────────────────────────────── */}
      {viewMode === "grid" && (
        <div className="file-grid">
          {sortedFiles.map((f) => (
            <div key={f.path} className="file-card">
              <div className="file-card-icon">
                <span className="file-icon pdf">PDF</span>
              </div>
              <a
                className="file-card-name"
                href={`/api/files/view/${encodeURIComponent(f.name)}`}
                target="_blank"
                rel="noopener noreferrer"
                title={f.name}
              >
                {f.name}
              </a>
              <div className="file-card-meta">
                <span className={`status-badge ${f.indexed ? "indexed" : "not-indexed"}`}>
                  {f.indexed ? "Indexed" : "Not Indexed"}
                </span>
                <span className="category-chip">{f.category}</span>
              </div>
              <div className="file-card-footer">
                <span>{f.added}</span>
                <span>·</span>
                <span>{formatFileSize(f.size)}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── List / Table View ─────────────────────────────────────── */}
      {viewMode === "list" && (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>File Name</th>
                <th>Status</th>
                <th>Category</th>
                <th>Added</th>
                <th>Size</th>
              </tr>
            </thead>
            <tbody>
              {sortedFiles.map((f) => (
                <tr key={f.path}>
                  <td>
                    <div className="file-cell">
                      <span className="file-icon pdf">PDF</span>
                      <div>
                        <a
                          className="file-name file-name-link"
                          href={`/api/files/view/${encodeURIComponent(f.name)}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          title={`Open ${f.name} in new tab`}
                        >
                          {f.name}
                        </a>
                      </div>
                    </div>
                  </td>
                  <td>
                    <span className={`status-badge ${f.indexed ? "indexed" : "not-indexed"}`}>
                      {f.indexed ? "Indexed" : "Not Indexed"}
                    </span>
                  </td>
                  <td>
                    <span className="category-chip">{f.category}</span>
                  </td>
                  <td style={{ color: "var(--text-secondary)", fontSize: "0.82rem" }}>{f.added}</td>
                  <td style={{ color: "var(--text-tertiary)", fontSize: "0.82rem" }}>{formatFileSize(f.size)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

/* ── Team View ───────────────────────────────────────────────── */
const TEAM_MEMBER = {
  name: "Ilkin Hamzayev",
  title: "AI Engineer",
  location: "Baku, Azerbaijan",
  bio: "AI Engineer who architected and developed the TechCorp Knowledge Base — a full-stack RAG platform powered by semantic search, cross-encoder reranking, and LLM-driven document analysis.",
  departments: DEPARTMENTS,
}

const TEAM_CORE_STACK = [
  { label: "Python / FastAPI",       icon: FileText },
  { label: "React 18 / Vite",        icon: LayoutDashboard },
  { label: "Qdrant Vector DB",       icon: Folder },
  { label: "FastEmbed (local)",      icon: FileText },
  { label: "Cross-Encoder Rerank",   icon: Target },
  { label: "LangChain / LangGraph",  icon: FileText },
  { label: "n8n Workflow Engine",    icon: RefreshCw },
  { label: "MCP Protocol (SSE)",     icon: ShieldCheck },
  { label: "Docker Compose",         icon: Folder },
  { label: "DeepSeek (LLM)",        icon: Users },
]

const TEAM_FEATURES = [
  { title: "Semantic Document Search",      desc: "Qdrant vector DB with cross-encoder reranking and sigmoid-normalized scores." },
  { title: "Multi-Turn RAG Chat",           desc: "Context-aware conversations with streaming SSE responses and source attribution." },
  { title: "RAG Evaluation Pipeline",       desc: "RAGAS metrics (context precision/recall, faithfulness, answer relevancy) with before/after comparison dashboard." },
  { title: "Parent-Child Chunking",         desc: "Two-pass retrieval: fine-grained child chunks for search, expanded parent chunks for LLM context." },
  { title: "Cross-Department Audit",        desc: "Batch-parallel LLM analysis across 9 policy topics × 6 departments." },
  { title: "Onboarding Plan Generator",     desc: "Few-Shot + Chain-of-Thought prompt pipeline producing structured 4-week plans." },
  { title: "Knowledge Gap Pipeline",        desc: "Full lifecycle: detection → n8n draft generation → approval → Qdrant indexing." },
  { title: "Smart Chat Router",             desc: "Pattern-match classifier routes simple queries to RAG and complex to n8n MCP agent." },
]

function TeamView({ onNavigate }) {
  return (
    <div className="team-view">
      <div className="team-layout">

        {/* ════ Left: Profile Panel ════ */}
        <div className="team-profile-panel">
          <div className="team-profile-card">

            {/* Avatar + online dot */}
            <div className="team-profile-avatar-wrap">
              <div className="team-profile-avatar">IH</div>
              <span className="team-status-dot" />
            </div>

            {/* Name & title */}
            <div className="team-profile-name">{TEAM_MEMBER.name}</div>
            <div className="team-profile-title">{TEAM_MEMBER.title}</div>

            {/* Action button */}
            <button className="team-profile-action"
              onClick={() => onNavigate("requests")}>
              <Briefcase size={15} />
              <span>View Knowledge Requests</span>
            </button>

            <div className="team-divider" />

            {/* Departments */}
            <div className="team-profile-section">
              <div className="team-profile-section-label">Departments</div>
              <div className="team-dept-tags">
                {TEAM_MEMBER.departments.map((d) => (
                  <span key={d} className="team-dept-tag">{d}</span>
                ))}
              </div>
            </div>

            <div className="team-divider" />

            {/* About */}
            <div className="team-profile-section">
              <div className="team-profile-section-label">About</div>
              <div className="team-profile-about">
                {TEAM_MEMBER.bio}
              </div>
              <div className="team-profile-meta">
                <span><MapPin size={13} /> {TEAM_MEMBER.location}</span>
              </div>
            </div>

          </div>
        </div>

        {/* ════ Right: Project Resume ════ */}
        <div className="team-feed-panel">

          {/* Headline */}
          <div className="team-feed-header">
            <div className="team-feed-headline">
              Full-stack RAG knowledge base serving 6 departments with semantic search, AI chat, audits, and automated onboarding
            </div>
          </div>

          {/* Stats row */}
          <div className="team-resume-stats">
            <div className="team-resume-stat">
              <span className="team-resume-stat-num">6</span>
              <span className="team-resume-stat-label">Departments</span>
            </div>
            <div className="team-resume-stat">
              <span className="team-resume-stat-num">23</span>
              <span className="team-resume-stat-label">Documents</span>
            </div>
            <div className="team-resume-stat">
              <span className="team-resume-stat-num">3</span>
              <span className="team-resume-stat-label">Docker Services</span>
            </div>
            <div className="team-resume-stat">
              <span className="team-resume-stat-num">15+</span>
              <span className="team-resume-stat-label">API Endpoints</span>
            </div>
          </div>

          {/* Core Stack */}
          <div className="team-resume-section">
            <div className="team-profile-section-label">Core Stack</div>
            <div className="team-dept-tags">
              {TEAM_CORE_STACK.map((item) => (
                <span key={item.label} className="team-dept-tag team-stack-tag">
                  <item.icon size={12} />
                  {item.label}
                </span>
              ))}
            </div>
          </div>

          {/* Features */}
          <div className="team-resume-section">
            <div className="team-profile-section-label">Features</div>
            <div className="team-features-grid">
              {TEAM_FEATURES.map((f) => (
                <div className="team-feature-card" key={f.title}>
                  <div className="team-feature-title">{f.title}</div>
                  <div className="team-feature-desc">{f.desc}</div>
                </div>
              ))}
            </div>
          </div>

        </div>
      </div>
    </div>
  )
}

/* ── Chat Panel (Right Column, collapsible) ────────────────────── */
const CHAT_SESSIONS_KEY = "tc_chat_sessions"
const BACKEND_STARTED_KEY = "tc_backend_started_at"

function loadSessions() {
  try {
    const raw = localStorage.getItem(CHAT_SESSIONS_KEY)
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}

function saveSessions(sessions) {
  try { localStorage.setItem(CHAT_SESSIONS_KEY, JSON.stringify(sessions)) } catch {}
}

function ChatPanel({ onMinimize, onGapSubmitted }) {
  const [sessions, setSessions] = useState(loadSessions)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [sessionId, setSessionId] = useState(generateSessionId)
  const [historyOpen, setHistoryOpen] = useState(false)
  const chatEnd = useRef(null)

  // Knowledge gap state
  const [gapData, setGapData] = useState(null)        // { suggested_department, question }
  const [showGapForm, setShowGapForm] = useState(false)
  const [gapName, setGapName] = useState("")
  const [gapMessage, setGapMessage] = useState("")
  const [gapSubmitted, setGapSubmitted] = useState(false)

  // Scroll to bottom on new messages
  useEffect(() => {
    chatEnd.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, loading])

  // Clear localStorage sessions if backend restarted (stale sessions)
  useEffect(() => {
    healthCheck()
      .then((data) => {
        const currentStarted = data.started_at
        const storedStarted = localStorage.getItem(BACKEND_STARTED_KEY)
        if (storedStarted && storedStarted !== currentStarted) {
          // Backend restarted — clear stale history
          localStorage.removeItem(CHAT_SESSIONS_KEY)
          setSessions([])
        }
        localStorage.setItem(BACKEND_STARTED_KEY, currentStarted)
      })
      .catch(() => {}) // ignore — backend might be down
  }, [])

  const saveCurrentSession = (msgs, id) => {
    if (msgs.length === 0) return
    const firstUser = msgs.find((m) => m.role === "user")
    const title = firstUser ? firstUser.content.slice(0, 45) : "New conversation"
    setSessions((prev) => {
      const filtered = prev.filter((s) => s.id !== id)
      const updated = [
        { id, title, messages: msgs, updatedAt: Date.now() },
        ...filtered,
      ]
      saveSessions(updated)
      return updated
    })
  }

  const loadSession = (s) => {
    // Save current before switching
    if (messages.length > 0) saveCurrentSession(messages, sessionId)
    setSessionId(s.id)
    setMessages(s.messages)
    setHistoryOpen(false)
  }

  const deleteSession = (e, id) => {
    e.stopPropagation()
    setSessions((prev) => {
      const updated = prev.filter((s) => s.id !== id)
      saveSessions(updated)
      // If deleting the active session, start fresh
      if (id === sessionId) {
        setMessages([])
        setSessionId(generateSessionId())
      }
      return updated
    })
  }

  const handleNewChat = () => {
    saveCurrentSession(messages, sessionId)
    setMessages([])
    setSessionId(generateSessionId())
  }

  const handleSend = async () => {
    const text = input.trim()
    if (!text || loading) return

    const userMsg = { role: "user", content: text }
    const assistantMsg = { role: "assistant", content: "", sources: [] }
    setMessages((prev) => [...prev, userMsg, assistantMsg])
    setInput("")
    setLoading(true)
    setGapData(null)
    setShowGapForm(false)
    setGapSubmitted(false)

    chatMessageSmartStream({
      message: text,
      sessionId,
      onToken: (token) => {
        setMessages((prev) => {
          const updated = [...prev]
          const last = updated[updated.length - 1]
          if (last.role === "assistant") {
            updated[updated.length - 1] = { ...last, content: last.content + token }
          }
          return updated
        })
      },
      onGap: ({ suggested_department, question }) => {
        setGapData({ suggested_department, question })
        setMessages((prev) => {
          const updated = [...prev]
          const last = updated[updated.length - 1]
          if (last.role === "assistant") {
            updated[updated.length - 1] = { ...last, gap: { suggested_department, question } }
          }
          return updated
        })
      },
      onDone: (sources, route) => {
        setMessages((prev) => {
          const updated = [...prev]
          const last = updated[updated.length - 1]
          if (last.role === "assistant") {
            updated[updated.length - 1] = { ...last, sources, route }
          }
          saveCurrentSession(updated, sessionId)
          return updated
        })
        setLoading(false)
      },
      onError: (errMsg) => {
        setMessages((prev) => {
          const updated = [...prev]
          const last = updated[updated.length - 1]
          if (last.role === "assistant") {
            updated[updated.length - 1] = {
              ...last,
              content: `Error: Could not reach backend. Make sure the API is running.`,
              isError: true,
            }
          }
          saveCurrentSession(updated, sessionId)
          return updated
        })
        setLoading(false)
      },
    })
  }

  const handleGapSubmit = async () => {
    if (!gapData) return
    try {
      await submitGapRequest({
        query: gapData.question,
        suggestedDepartment: gapData.suggested_department,
        requesterName: gapName.trim() || "Anonymous",
        message: gapMessage.trim(),
      })
      setGapSubmitted(true)
      onGapSubmitted?.()
    } catch (e) {
      console.error("Failed to submit gap request:", e)
    }
  }

  const handleGapDismiss = () => {
    setGapData(null)
    setShowGapForm(false)
    setGapSubmitted(false)
  }

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const formatTime = (ts) => {
    const diff = Date.now() - ts
    const mins = Math.floor(diff / 60000)
    if (mins < 1) return "Just now"
    if (mins < 60) return `${mins}m ago`
    const hours = Math.floor(mins / 60)
    if (hours < 24) return `${hours}h ago`
    const days = Math.floor(hours / 24)
    if (days < 7) return `${days}d ago`
    return new Date(ts).toLocaleDateString()
  }

  return (
    <aside className="chat-panel">
      {/* Header */}
      <div className="chat-panel-header">
        <button
          className={`btn-chat-history ${historyOpen ? "active" : ""}`}
          onClick={() => setHistoryOpen(!historyOpen)}
          title="Chat history"
        >
          <span>☰</span>
        </button>
        <div className="chat-panel-title">
          <span className="chat-panel-icon">🤖</span>
          <span>Tech Corp AI Assistant</span>
        </div>
        <div className="chat-panel-actions">
          <button className="btn-chat-new" onClick={handleNewChat} title="Start a new conversation">
            <span>+</span>
            <span>New Chat</span>
          </button>
          <button className="btn-chat-minimize" onClick={onMinimize} title="Minimize chat">
            <span className="minimize-icon">─</span>
          </button>
        </div>
      </div>

      <div className="chat-body">
        {/* History Sidebar */}
        {historyOpen && (
          <div className="chat-history-sidebar">
            <div className="chat-history-header">
              <span>Chat History</span>
              <button
                className="chat-history-close"
                onClick={() => setHistoryOpen(false)}
              >
                ✕
              </button>
            </div>
            <div className="chat-history-list">
              {sessions.length === 0 && (
                <div className="chat-history-empty">No conversations yet</div>
              )}
              {sessions.map((s) => (
                <div
                  key={s.id}
                  className={`chat-history-item ${s.id === sessionId ? "active" : ""}`}
                  onClick={() => loadSession(s)}
                >
                  <div className="chat-history-item-title">{s.title}</div>
                  <div className="chat-history-item-time">{formatTime(s.updatedAt)}</div>
                  <button
                    className="chat-history-delete"
                    onClick={(e) => deleteSession(e, s.id)}
                    title="Delete"
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Messages */}
        <div className="chat-messages">
          {messages.length === 0 && (
            <div className="welcome">
              <div className="welcome-icon">💬</div>
              <h2>Ask a question about company documents</h2>
              <p>
                Ask anything about TechCorp policies, engineering docs,
                security procedures, and more.
              </p>
              <div className="suggestions">
                {[
                  "What are the production access levels?",
                  "How does disaster recovery work?",
                  "What is the incident escalation process?",
                ].map((q) => (
                  <button
                    key={q}
                    className="suggestion-chip"
                    onClick={() => setInput(q)}
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <ChatMessageBubble key={i} msg={msg} onGapSubmitted={onGapSubmitted} />
          ))}

          {loading && (
            <div className="message">
              <div className="message-avatar">🤖</div>
              <div className="message-body">
                <div className="typing">
                  <span /><span /><span />
                </div>
              </div>
            </div>
          )}

          <div ref={chatEnd} />
        </div>
      </div>

      {/* Input */}
      <div className="chat-input-bar">
        <textarea
          className="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask a question about your documents..."
          rows={1}
          disabled={loading}
        />
        <button
          className="btn-send"
          onClick={handleSend}
          disabled={loading || !input.trim()}
        >
          ▶
        </button>
      </div>
    </aside>
  )
}

/* ── Chat Message Bubble ─────────────────────────────────────── */
function ChatMessageBubble({ msg, onGapAction, onGapSubmitted }) {
  const isUser = msg.role === "user"
  const [sourcesOpen, setSourcesOpen] = useState(false)
  const [gapFormOpen, setGapFormOpen] = useState(false)
  const [gapDismissed, setGapDismissed] = useState(false)
  const [gapName, setGapName] = useState("")
  const [gapMessage, setGapMessage] = useState("")
  const [gapSubmitted, setGapSubmitted] = useState(false)
  const hasSources = msg.sources && msg.sources.length > 0
  const hasMultiple = hasSources && msg.sources.length > 1
  const mainSource = hasSources ? msg.sources[0] : null
  const otherSources = hasMultiple ? msg.sources.slice(1) : []
  const hasGap = !gapDismissed && msg.gap && msg.gap.suggested_department

  const handleGapSubmit = async () => {
    if (!msg.gap) return
    try {
      await submitGapRequest({
        query: msg.gap.question,
        suggestedDepartment: msg.gap.suggested_department,
        requesterName: gapName.trim() || "Anonymous",
        message: gapMessage.trim(),
      })
      setGapSubmitted(true)
      onGapSubmitted?.()
    } catch (e) {
      console.error("Failed to submit gap request:", e)
    }
  }

  return (
    <div className={`message ${isUser ? "user" : "assistant"} ${msg.isError ? "error" : ""}`}>
      <div className="message-avatar">{isUser ? "👤" : "🤖"}</div>
      <div className="message-body">
        <div className="message-content">{msg.content}</div>

        {/* Knowledge Gap Card */}
        {hasGap && !gapSubmitted && (
          <div className="gap-card">
            <div className="gap-card-header">
              <span className="gap-card-icon">💡</span>
              <span className="gap-card-title">I couldn't find official docs on this.</span>
            </div>
            <p className="gap-card-text">
              This seems related to <strong>{msg.gap.suggested_department.replace(/_/g, " ")}</strong> department.
            </p>
            <div className="gap-card-actions">
              <button
                className="btn-gap-send"
                onClick={() => setGapFormOpen(!gapFormOpen)}
              >
                <span>📩</span>
                <span>Send request to {msg.gap.suggested_department.replace(/_/g, " ")} team</span>
              </button>
              <button
                className="btn-gap-dismiss"
                onClick={() => setGapDismissed(true)}
              >
                ✕
              </button>
            </div>

            {/* Inline mini-form */}
            {gapFormOpen && (
              <div className="gap-form">
                <input
                  className="gap-form-input"
                  type="text"
                  placeholder="Your name (optional)"
                  value={gapName}
                  onChange={(e) => setGapName(e.target.value)}
                />
                <textarea
                  className="gap-form-textarea"
                  placeholder="Add more details about what you were looking for..."
                  value={gapMessage}
                  onChange={(e) => setGapMessage(e.target.value)}
                  rows={2}
                />
                <div className="gap-form-actions">
                  <button
                    className="btn-primary btn-sm"
                    onClick={handleGapSubmit}
                  >
                    Submit Request
                  </button>
                  <button
                    className="btn-secondary btn-sm"
                    onClick={() => setGapFormOpen(false)}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {hasGap && gapSubmitted && (
          <div className="gap-card gap-submitted">
            <div className="gap-card-header">
              <span className="gap-card-icon">✅</span>
              <span className="gap-card-title">Request submitted!</span>
            </div>
            <p className="gap-card-text">
              Track it in <strong>📋 Requests & Approvals</strong>.
            </p>
          </div>
        )}

        {/* Multiple sources: main source + other sources section */}
        {hasMultiple && (
          <div className="sources">
            <div className="main-source-label">📎 Main source</div>
            <SourceCard source={mainSource} />

            <div className="other-sources-section">
              <button
                className="sources-toggle"
                onClick={() => setSourcesOpen(!sourcesOpen)}
              >
                🔍 Other sources to check for more info ({otherSources.length})
                <span className={`arrow ${sourcesOpen ? "open" : ""}`}>▾</span>
              </button>
              {sourcesOpen && (
                <div className="sources-list">
                  {otherSources.map((s, i) => (
                    <SourceCard key={i} source={s} />
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Single source: normal toggle */}
        {hasSources && !hasMultiple && (
          <div className="sources">
            <button
              className="sources-toggle"
              onClick={() => setSourcesOpen(!sourcesOpen)}
            >
              📎 1 source
              <span className={`arrow ${sourcesOpen ? "open" : ""}`}>▾</span>
            </button>
            {sourcesOpen && (
              <div className="sources-list">
                <SourceCard source={mainSource} />
              </div>
            )}
          </div>
        )}

        <div className="message-timestamp">Just now</div>
      </div>
    </div>
  )
}

/* ── Source Card ─────────────────────────────────────────────── */
function SourceCard({ source }) {
  // Handle both object sources (from RAG) and string sources (from n8n/MCP)
  if (typeof source === "string") {
    return (
      <div className="source-card">
        <div className="source-header">
          <span className="source-category">document</span>
        </div>
        <div className="source-file">{source}</div>
      </div>
    )
  }
  const pct = typeof source.score === "number" ? Math.round(source.score) : 0
  const filename = (source.source || "").split("/").pop()
  return (
    <div className="source-card">
      <div className="source-header">
        <span className="source-category">{source.category || "document"}</span>
        <span className="source-score">{pct}%</span>
      </div>
      <a
        className="source-file-link"
        href={`/api/files/view/${encodeURIComponent(filename)}`}
        target="_blank"
        rel="noopener noreferrer"
        title={source.source || ""}
      >
        {filename}
      </a>
      <div className="source-pct-bar">
        <div className="source-pct-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="source-text">{(source.text || "").slice(0, 180)}...</div>
    </div>
  )
}