
const BASE = "/api"

// ── Smart Chat with Classifier Routing ──────────────────────────
// simple queries → direct RAG (fast, 2-3s)
// complex queries → n8n + MCP agent (deep, 8-12s)

export async function chatMessageSmartStream({ message, sessionId = "default", onToken, onDone, onError, onGap }) {
  try {
    const res = await fetch(`${BASE}/chat/smart/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id: sessionId }),
    })

    if (!res.ok) throw new Error(`Smart stream failed: ${res.status}`)

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ""

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split("\n")
      buffer = lines.pop() || ""

      for (const line of lines) {
        if (line.startsWith("data: ")) {
          try {
            const event = JSON.parse(line.slice(6))
            if (event.type === "gap") {
              if (onGap) onGap({ suggested_department: event.suggested_department, question: event.question })
            } else if (event.type === "token") {
              onToken(event.content)
            } else if (event.type === "done") {
              onDone(event.sources || [], event.route)
            } else if (event.type === "route") {
              // optional: show routing decision
            }
          } catch (e) {
            // skip incomplete JSON
          }
        }
      }
    }
  } catch (err) {
    onError(err.message)
  }
}

export async function fetchFiles() {
  const res = await fetch(`${BASE}/files`)
  if (!res.ok) throw new Error(`Failed to fetch files: ${res.status}`)
  return res.json()
}

export async function fetchDepartments() {
  const res = await fetch(`${BASE}/departments`)
  if (!res.ok) throw new Error(`Failed to fetch departments: ${res.status}`)
  return res.json()
}

export async function uploadFile(file, category) {
  const formData = new FormData()
  formData.append("file", file)
  formData.append("category", category)

  const res = await fetch(`${BASE}/files/upload`, {
    method: "POST",
    body: formData,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `Upload failed: ${res.status}`)
  }
  return res.json()
}

export async function healthCheck() {
  const res = await fetch(`${BASE}/health`)
  return res.json()
}

export function formatFileSize(bytes) {
  if (bytes === 0) return "0 B"
  const units = ["B", "KB", "MB", "GB"]
  const k = 1024
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  const value = bytes / Math.pow(k, i)
  return `${value.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

// ── Document Audit (backend endpoint, parallel LLM batches) ──────
export async function runDocumentAudit({ departments }) {
  const res = await fetch(`${BASE}/audit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ departments }),
  })
  if (!res.ok) throw new Error(`Audit failed: ${res.status}`)
  return res.json()
}

// ── Onboarding / Streaming (direct FastAPI) ────────
export async function generateOnboardingPlanStream({ role, department, experience, onToken, onDone, onError }) {
  try {
    const res = await fetch(`${BASE}/onboarding/generate/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role, department, experience }),
    })

    if (!res.ok) throw new Error(`Onboarding stream failed: ${res.status}`)

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ""

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split("\n")
      buffer = lines.pop() || ""

      for (const line of lines) {
        if (line.startsWith("data: ")) {
          try {
            const event = JSON.parse(line.slice(6))
            if (event.type === "token") {
              onToken(event.content)
            } else if (event.type === "done") {
              onDone(event.sources || [], event.plan)
            }
          } catch (e) {
            // skip incomplete JSON
          }
        }
      }
    }
  } catch (err) {
    onError(err.message)
  }
}

// ── n8n-powered streaming (FastAPI calls n8n, streams LLM tokens) ─
export async function generateOnboardingN8nStream({ role, department, experience, onToken, onDone, onError }) {
  try {
    const res = await fetch(`${BASE}/onboarding/n8n/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role, department, experience }),
    })

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(err.detail || `Stream failed: ${res.status}`)
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ""

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split("\n")
      buffer = lines.pop() || ""

      for (const line of lines) {
        if (line.startsWith("data: ")) {
          try {
            const event = JSON.parse(line.slice(6))
            if (event.type === "context_ready") {
              // n8n retrieval complete, tokens about to start
            } else if (event.type === "token") {
              onToken(event.content)
            } else if (event.type === "done") {
              onDone(null, event.plan)
            }
          } catch (e) {
            // skip incomplete JSON
          }
        }
      }
    }
  } catch (err) {
    onError(err.message)
  }
}

// ── Knowledge Gap Requests ───────────────────────────────────────
export async function submitGapRequest({ query, suggestedDepartment, requesterName, message }) {
  const res = await fetch(`${BASE}/knowledge-gap`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query,
      suggested_department: suggestedDepartment,
      requester_name: requesterName,
      message,
    }),
  })
  if (!res.ok) throw new Error(`Gap request failed: ${res.status}`)
  return res.json()
}

export async function fetchGapRequests(status = null) {
  const params = status ? `?status=${status}` : ""
  const res = await fetch(`${BASE}/knowledge-gap${params}`)
  if (!res.ok) throw new Error(`Fetch gap requests failed: ${res.status}`)
  return res.json()
}

// Triggers n8n webhook to generate a draft (status stays "pending" until callback)
export async function approveGapRequest(gapId) {
  const res = await fetch(`${BASE}/knowledge-gap/${gapId}/approve`, {
    method: "POST",
  })
  if (!res.ok) throw new Error(`Approve gap request failed: ${res.status}`)
  return res.json()
}

// Confirms a draft_ready item — writes to department folder and indexes in Qdrant
export async function confirmGapRequest(gapId) {
  const res = await fetch(`${BASE}/knowledge-gap/${gapId}/confirm`, {
    method: "POST",
  })
  if (!res.ok) throw new Error(`Confirm gap request failed: ${res.status}`)
  return res.json()
}

export async function deleteGapRequest(gapId) {
  const res = await fetch(`${BASE}/knowledge-gap/${gapId}`, {
    method: "DELETE",
  })
  if (!res.ok) throw new Error(`Delete gap request failed: ${res.status}`)
  return res.json()
}
