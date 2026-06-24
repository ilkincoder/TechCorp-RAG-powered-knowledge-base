import { useState, useEffect } from "react"
import {
  RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar,
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from "recharts"
import {
  BarChart3, TrendingUp, TrendingDown, ChevronDown, ChevronRight,
  Clock, FileText, Target, ShieldCheck, AlertCircle,
} from "lucide-react"

const METRIC_LABELS = {
  context_precision: "Context Precision",
  context_recall: "Context Recall",
  faithfulness: "Faithfulness",
  answer_relevancy: "Answer Relevancy",
}

function formatPct(val) {
  return `${(val * 100).toFixed(1)}%`
}

function formatMs(val) {
  if (val >= 1000) return `${(val / 1000).toFixed(1)}s`
  return `${Math.round(val)}ms`
}

function delta(val1, val2) {
  const diff = val2 - val1
  const pct = val1 !== 0 ? ((diff / val1) * 100) : 0
  return { diff, pct, positive: diff > 0 }
}

// ── KPI Card ────────────────────────────────────────────────────
function KPICard({ label, icon, v1Val, v2Val, format, higherIsBetter = true }) {
  const d = delta(v1Val, v2Val)
  const isGood = higherIsBetter ? d.positive : !d.positive
  const formattedV1 = format ? format(v1Val) : v1Val
  const formattedV2 = format ? format(v2Val) : v2Val

  return (
    <div className="eval-kpi-card">
      <div className="eval-kpi-header">
        <span className="eval-kpi-icon">{icon}</span>
        <span className="eval-kpi-label">{label}</span>
      </div>
      <div className="eval-kpi-values">
        <div className="eval-kpi-pair">
          <span className="eval-kpi-metric-label">V1</span>
          <span className="eval-kpi-value">{formattedV1}</span>
        </div>
        <div className="eval-kpi-pair">
          <span className="eval-kpi-metric-label">V2</span>
          <span className="eval-kpi-value">{formattedV2}</span>
        </div>
      </div>
      <div className={`eval-delta-badge ${isGood ? "eval-delta-positive" : "eval-delta-negative"}`}>
        {d.positive ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
        <span>{d.positive ? "+" : ""}{d.pct.toFixed(1)}%</span>
      </div>
    </div>
  )
}

// ── Trace Row ───────────────────────────────────────────────────
function TraceRow({ trace, index }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="eval-trace-row">
      <div className="eval-trace-summary" onClick={() => setOpen(!open)}>
        <span className="eval-trace-chevron">
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>
        <span className="eval-trace-index">#{index + 1}</span>
        <span className="eval-trace-query">{trace.query}</span>
        <span className="eval-trace-sources">
          {open ? "" : trace.source_pdf}
        </span>
      </div>
      {open && (
        <div className="eval-trace-detail">
          <div className="eval-trace-columns">
            {/* V1 column */}
            <div className="eval-trace-col">
              <h4 className="eval-trace-col-title">V1 — Naive Chunking</h4>
              <div className="eval-trace-meta">
                <Clock size={12} /> {formatMs(trace.baseline.retrieval_ms)} retrieval
                {" · "}
                {formatMs(trace.baseline.generation_ms)} generation
              </div>
              <div className="eval-trace-chunks">
                <span className="eval-trace-section-label">Retrieved Chunks:</span>
                {trace.baseline.chunks.map((c, i) => (
                  <div key={i} className="eval-chunk">
                    <span className="eval-chunk-source">{c.source}</span>
                    <span className="eval-chunk-score">score: {c.score.toFixed(2)}</span>
                    <p className="eval-chunk-text">{c.text}</p>
                  </div>
                ))}
              </div>
              <div className="eval-trace-answer">
                <span className="eval-trace-section-label">Generated Answer:</span>
                <p>{trace.baseline.answer}</p>
              </div>
            </div>
            {/* V2 column */}
            <div className="eval-trace-col">
              <h4 className="eval-trace-col-title">V2 — Parent‑Child Retrieval</h4>
              <div className="eval-trace-meta">
                <Clock size={12} /> {formatMs(trace.parent_child.retrieval_ms)} retrieval
                {" · "}
                {formatMs(trace.parent_child.generation_ms)} generation
              </div>
              <div className="eval-trace-chunks">
                <span className="eval-trace-section-label">Retrieved Parent Chunks:</span>
                {trace.parent_child.chunks.map((c, i) => (
                  <div key={i} className="eval-chunk">
                    <span className="eval-chunk-source">{c.source}</span>
                    <p className="eval-chunk-text">{c.text}</p>
                  </div>
                ))}
              </div>
              <div className="eval-trace-answer">
                <span className="eval-trace-section-label">Generated Answer:</span>
                <p>{trace.parent_child.answer}</p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Main Dashboard ──────────────────────────────────────────────
export default function EvalDashboard() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch("/eval_results.json")
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then((json) => {
        setData(json)
        setLoading(false)
      })
      .catch((err) => {
        setError(err.message)
        setLoading(false)
      })
  }, [])

  // ── Loading ──────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="eval-dashboard">
        <div className="eval-loading">
          <div className="eval-spinner" />
          <p>Loading evaluation results...</p>
        </div>
      </div>
    )
  }

  // ── Error / No Data ───────────────────────────────────────────
  if (error || !data) {
    return (
      <div className="eval-dashboard">
        <div className="eval-empty">
          <AlertCircle size={48} strokeWidth={1.5} />
          <h2>No Evaluation Data</h2>
          <p>
            Run the evaluation script to generate results:
          </p>
          <code>python src/evaluation/run_eval.py</code>
          {error && <p className="eval-error-detail">Error: {error}</p>}
        </div>
      </div>
    )
  }

  const bl = data.baseline.metrics
  const pc = data.parent_child.metrics

  // ── Radar chart data ──────────────────────────────────────────
  const radarData = ["context_precision", "context_recall", "faithfulness", "answer_relevancy"].map((k) => ({
    metric: METRIC_LABELS[k],
    Baseline: +(bl[k] * 100).toFixed(1),
    "Parent-Child": +(pc[k] * 100).toFixed(1),
  }))

  // ── Bar chart data ────────────────────────────────────────────
  const barData = [
    { name: "Latency (ms)", Baseline: bl.latency_ms, "Parent-Child": pc.latency_ms },
    { name: "Tokens / query", Baseline: bl.token_count, "Parent-Child": pc.token_count },
  ]

  return (
    <div className="eval-dashboard">
      {/* Header */}
      <div className="eval-header">
        <h2>
          <BarChart3 size={22} /> RAG Evaluation Dashboard
        </h2>
        <p>
          Real RAGAS metrics comparing V1 (naive 500-char chunks) vs V2
          (parent‑child retrieval) across {data.num_questions} questions
          generated from {data.pdfs_sampled} TechCorp documents.
          <span className="eval-timestamp"> · Run at {data.generated_at}</span>
        </p>
      </div>

      {/* KPI Cards */}
      <div className="eval-kpi-grid">
        <KPICard
          label="Context Precision"
          icon={<Target size={16} />}
          v1Val={bl.context_precision}
          v2Val={pc.context_precision}
          format={formatPct}
        />
        <KPICard
          label="Context Recall"
          icon={<FileText size={16} />}
          v1Val={bl.context_recall}
          v2Val={pc.context_recall}
          format={formatPct}
        />
        <KPICard
          label="Faithfulness"
          icon={<ShieldCheck size={16} />}
          v1Val={bl.faithfulness}
          v2Val={pc.faithfulness}
          format={formatPct}
        />
        <KPICard
          label="Answer Relevancy"
          icon={<Target size={16} />}
          v1Val={bl.answer_relevancy}
          v2Val={pc.answer_relevancy}
          format={formatPct}
        />
        <KPICard
          label="Latency"
          icon={<Clock size={16} />}
          v1Val={bl.latency_ms}
          v2Val={pc.latency_ms}
          format={formatMs}
          higherIsBetter={false}
        />
        <KPICard
          label="Token Usage"
          icon={<FileText size={16} />}
          v1Val={bl.token_count}
          v2Val={pc.token_count}
          format={(v) => `~${Math.round(v)} tok`}
          higherIsBetter={false}
        />
      </div>

      {/* Charts */}
      <div className="eval-charts-grid">
        <div className="eval-chart-container">
          <h3>Quality Metrics</h3>
          <ResponsiveContainer width="100%" height={350}>
            <RadarChart data={radarData}>
              <PolarGrid stroke="#21262d" />
              <PolarAngleAxis dataKey="metric" tick={{ fill: "#8b949e", fontSize: 12 }} />
              <PolarRadiusAxis angle={30} domain={[0, 100]} tick={{ fill: "#6e7681", fontSize: 10 }} />
              <Radar name="Baseline" dataKey="Baseline" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.15} strokeWidth={2} />
              <Radar name="Parent-Child" dataKey="Parent-Child" stroke="#22c55e" fill="#22c55e" fillOpacity={0.15} strokeWidth={2} />
              <Legend wrapperStyle={{ color: "#e6edf3" }} />
            </RadarChart>
          </ResponsiveContainer>
        </div>

        <div className="eval-chart-container">
          <h3>Performance Overhead</h3>
          <ResponsiveContainer width="100%" height={350}>
            <BarChart data={barData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#21262d" />
              <XAxis dataKey="name" tick={{ fill: "#8b949e", fontSize: 12 }} />
              <YAxis tick={{ fill: "#6e7681", fontSize: 10 }} />
              <Tooltip
                contentStyle={{ background: "#161b22", border: "1px solid #21262d", borderRadius: 8, color: "#e6edf3" }}
              />
              <Legend wrapperStyle={{ color: "#e6edf3" }} />
              <Bar dataKey="Baseline" fill="#3b82f6" radius={[4, 4, 0, 0]} />
              <Bar dataKey="Parent-Child" fill="#22c55e" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Trace Viewer */}
      <div className="eval-trace-section">
        <h3>Query Traces ({data.traces.length})</h3>
        <p className="eval-trace-hint">Click a row to inspect chunks and answers</p>
        <div className="eval-trace-list">
          {data.traces.map((trace, i) => (
            <TraceRow key={i} trace={trace} index={i} />
          ))}
        </div>
      </div>
    </div>
  )
}