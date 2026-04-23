import { useState, useEffect } from 'react'
import './App.css'



function StatusBadge({ status }) {
  const config = {
    pending: { color: "#94a3b8", icon: '◷' },
    queued: { color: "#60a5fa", icon: '⏳' },
    running: { color: "#fbbf24", icon: '▶' },
    completed: { color: "#34d399", icon: '✓' },
    failed: { color: "#f87171", icon: '✗' },
    retrying: { color: "#c084fc", icon: '⟳' },
    dead: { color: "#ef4444", icon: '☠' },
  }
  const cfg = config[status] || config.pending

  return (
    <span className="status-badge" style={{
      color: cfg.color,
      background: `${cfg.color}15`,
      border: `1px solid ${cfg.color}33`,
    }}>
      <span>{cfg.icon}</span> {status.toUpperCase()}
    </span>
  )
}

function PriorityBadge({ priority }) {
  const labels = { 1: "LOW", 5: "MEDIUM", 10: "HIGH", 20: "CRITICAL" }
  const colors = { 1: "#94a3b8", 5: "#60a5fa", 10: "#fbbf24", 20: "#ef4444" }
  const label = labels[priority] || priority
  const color = colors[priority] || "#94a3b8"

  return (
    <span className="priority-badge" style={{
      color: color,
      background: `${color}15`,
    }}>
      {label}
    </span>
  )
}

// const API_URL = "http://localhost:8000"
// const API_URL = "http://20.240.221.65:8000"
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function App() {

  // State variables
  // const [apiKey, setApiKey] = useState(localStorage.getItem("qf_api_key") || "")
  const [tasks, setTasks] = useState([])
  const [keyInput, setKeyInput] = useState("")
  const [loggedIn, setLoggedIn] = useState(false) // New state to track login status
  const [error, setError] = useState("")
  const [step, setStep] = useState("choose")  // 'choose', 'new', 'existing'
  const [loading, setLoading] = useState(false)
  const [createdKey, setCreatedKey] = useState("") // Store created API key to show to user
  const [showSubmit, setShowSubmit] = useState(false) // Control visibility of submit button on task form
  const [tenantNameInput, setTenantNameInput] = useState("") // State for tenant name input in create tenant form
  const [tenantName, setTenantName] = useState("") // Store tenant name after login
  const [activeTab, setActiveTab] = useState("tasks")  // "tasks" or "dlq"
  const [dlqTasks, setDlqTasks] = useState([])
  const [statusFilter, setStatusFilter] = useState(null) // New state to track status filter in task list (null means no filter)
  const [toasts, setToasts] = useState([]) // State for toast notifications
  const [page, setPage] = useState(1) // State for pagination
  const [totalTasks, setTotalTasks] = useState(0) // Total number of tasks, used for pagination
  const [adminTenants, setAdminTenants] = useState([]) // List of tenants for admin view
  const [adminTasks, setAdminTasks] = useState([]) // List of all tasks across tenants for admin view
  const [adminStats, setAdminStats] = useState(null) // Stats for admin dashboard
  const [isAdmin, setIsAdmin] = useState(false) // Flag to indicate if the logged-in tenant has admin privileges or not
  const pageSize = 20

  // State for new task form
  const [submitForm, setSubmitForm] = useState({
    task_name: "send_email",
    priority: 5,
    delay_seconds: 0,
    max_retries: 3,
    // Email fields
    to: "user@example.com",
    subject: "Test Email",
    email_body: "Hello from QueueFlow",
    // Image fields
    image_url: "https://picsum.photos/1200/800.jpg",
    width: 400,
    height: 300,
    // Report fields
    report_type: "summary",
    callback_url: "",
  })

  // Stats for dashboard summary cards
  const [stats, setStats] = useState({
    total: 0, queued: 0, running: 0, completed: 0,
    failed: 0, retrying: 0, dead: 0,
  })

  // Instead of the static error message that sits on the page, toasts pop up in the corner and auto-dismiss after a few seconds.
  const addToast = (message, type = "error") => {
    console.log("TOAST:", message, type)
    const id = Date.now()
    setToasts(prev => [...prev, { id, message, type }])
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id))
    }, 5000) // Toast will disappear after 5 seconds
  }

  // Utility function to copy text to clipboard, with fallback for older browsers. Allows user to copy new API key.
  const copyToClipboard = (text) => {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text)
    }
    else {
      const textarea = document.createElement("textarea")
      textarea.value = text
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand("copy")
      document.body.removeChild(textarea)
    }
  }

  const saveKey = async () => {
    if (!keyInput.trim()) return
    setLoading(true)
    setError("")
    try {
      const res = await fetch(`${API_URL}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ api_key: keyInput.trim() }),
      })
      if (!res.ok) throw new Error("Invalid API key")
      const data = await res.json()
      setLoggedIn(true)
      fetchAdminStats() // Check if user is admin and fetch stats if so
      setTenantName(data.tenant_name)
    }
    catch (errData) {
      setError(errData.message)
    }
    finally {
      setLoading(false)
    }
  }

  const logout = async () => {
    await fetch(`${API_URL}/auth/logout`, {
      method: "POST",
      credentials: "include",
    })
    setLoggedIn(false)
    setTenantName("")
    setTenantNameInput("")
    setStep("choose")
    setStats({
      total: 0, queued: 0, running: 0, completed: 0,
      failed: 0, retrying: 0, dead: 0,
    })
  }

  // Check if user has a valid session on page load.
  useEffect(() => {
    const checkSession = async () => {
      try {
        const res = await fetch(`${API_URL}/tasks/?page_size=1`, {
          credentials: "include",
        })
        if (res.ok) {
          setLoggedIn(true)
          fetchAdminStats() // Check if user is admin and fetch stats if so
        }
      }
      catch (errData) {
        // No valid session, stay on login screen
      }
    }
    checkSession()
  }, [])


  useEffect(() => {
    if (!loggedIn) return

    const fetchTasks = async () => {
      try {
        const response = await fetch(`${API_URL}/tasks/?page=${page}&page_size=${pageSize}`, {
          credentials: "include",
        })
        if (response.status === 401) {
          setLoggedIn(false)
          addToast("Session expired. Please log in again.", "error")
          return
        }
        if (!response.ok) throw new Error("Failed to fetch tasks")
        const data = await response.json()
        setTasks(data.tasks)
        setTotalTasks(data.total)
      }
      catch (err) {
        setError(err.message)
      }
    }

    fetchTasks()
    if (activeTab === "dlq") fetchDlq()

    const interval = setInterval(() => {
      fetchTasks()
      if (activeTab === "dlq") fetchDlq()
      if (isAdmin) fetchAdminStats() // Refresh admin stats on the same interval to keep them up to date
    }, 5000)

    return () => clearInterval(interval)
  }, [loggedIn, activeTab, page])

  const createTenant = async () => {
    if (!tenantNameInput.trim()) { setError("Tenant name is required"); return }
    setLoading(true)
    setError("")
    try {
      const response1 = await fetch(`${API_URL}/tenants/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: tenantNameInput.trim() }),
      })
      if (!response1.ok) {
        const errData = await response1.json()
        throw new Error(errData.detail || "Failed to create tenant")
      }
      const tenant = await response1.json()

      const response2 = await fetch(`${API_URL}/tenants/${tenant.id}/api-keys`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label: "dashboard" }),
      })
      if (!response2.ok) {
        const errData = await response2.json()
        throw new Error(errData.detail || "Failed to create API key")
      }
      const apiKeyData = await response2.json()
      setCreatedKey(apiKeyData.key) // Store the created API key to show the user
    }
    catch (errData) {
      setError(errData.message)
    }
    finally {
      setLoading(false)
    }
  }

  const continueAfterCreate = async () => {
    setLoading(true)
    setError("")
    try {
      // Login with the new key(sets HTTP-only cookie)
      const response3 = await fetch(`${API_URL}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ api_key: createdKey }),
      })
      if (!response3.ok) {
        const errData = await response3.json()
        throw new Error(errData.detail || "Failed to login with new API key")
      }
      const loginData = await response3.json()
      setLoggedIn(true)
      fetchAdminStats() // Check if user is admin and fetch stats if so
      setTenantName(loginData.tenant_name)
      setCreatedKey("") // Clear the created key from state after successful login
    }
    catch (errData) {
      setError(errData.message)
    }
    finally {
      setLoading(false)
    }
  }

  const submitTask = async () => {
    setLoading(true)
    setError("")
    try {
      let payload = {}

      if (submitForm.task_name === "send_email") {
        payload = {
          to: submitForm.to,
          subject: submitForm.subject,
          body: submitForm.email_body,
        }
      } else if (submitForm.task_name === "process_image") {
        payload = {
          image_url: submitForm.image_url,
          width: parseInt(submitForm.width),
          height: parseInt(submitForm.height),
        }
      } else if (submitForm.task_name === "generate_report") {
        payload = {
          report_type: submitForm.report_type,
        }
      }

      const body = {
        task_name: submitForm.task_name,
        priority: submitForm.priority,
        max_retries: submitForm.max_retries,
        payload: payload,
      }

      if (submitForm.delay_seconds) {
        body.delay_seconds = parseInt(submitForm.delay_seconds)
      }

      // Only include callback_url if it's not empty after trimming whitespace. This way we avoid sending an empty string to the server which might cause validation errors if the server expects a valid URL or null.
      if (submitForm.callback_url.trim()) {
        body.callback_url = submitForm.callback_url.trim()
      }

      const res = await fetch(`${API_URL}/tasks/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        const errData = await res.json()
        throw new Error(errData.detail || "Failed to submit task")
      }

      setShowSubmit(false)

      addToast("Task submitted successfully", "success")
    }
    catch (errData) {
      addToast(errData.message, "error")
    }
    finally {
      setLoading(false)
    }
  }

  const cancelTask = async (taskId) => {
    try {
      const response = await fetch(`${API_URL}/tasks/${taskId}/cancel`, {
        method: "POST",
        credentials: "include",
      })
      if (!response.ok) {
        const errData = await response.json()
        throw new Error(errData.detail || "Failed to cancel task")
      }

      addToast("Task cancelled", "error")
    }
    catch (errData) {
      addToast(errData.message, "error")
    }
  }

  const retryTask = async (taskId) => {
    try {
      const response = await fetch(`${API_URL}/tasks/${taskId}/retry`, {
        method: "POST",
        credentials: "include",
      })
      if (!response.ok) {
        const errData = await response.json()
        throw new Error(errData.detail || "Failed to retry task")
      }
      addToast("Task queued for retry", "info")
    }
    catch (errData) {
      addToast(errData.message, "error")
    }
  }

  const downloadReport = async (taskId) => {
    try {
      const res = await fetch(`${API_URL}/tasks/${taskId}/download`, {
        credentials: "include",
      })
      if (!res.ok) throw new Error("Download failed")
      const blob = await res.blob()
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `queueflow_report_${taskId.substring(0, 8)}.pdf`
      a.click()
      window.URL.revokeObjectURL(url)
    } catch (errData) {
      addToast(errData.message, "error")
    }
  }

  const fetchDlq = async () => {
    try {
      const res = await fetch(`${API_URL}/dlq`, {
        credentials: "include",
      })
      if (!res.ok) throw new Error("Failed to fetch DLQ")
      const data = await res.json()
      setDlqTasks(data)
    } catch (e) {
      setError(e.message)
    }
  }

  const retryAllDlq = async () => {
    try {
      const res = await fetch(`${API_URL}/dlq/retry-all`, {
        method: "POST",
        credentials: "include",
      })
      if (!res.ok) throw new Error("Failed to retry DLQ tasks")
      const data = await res.json()
      addToast(`Retried ${data.replayed} tasks`, "info")
      setError("")
      fetchDlq()
    } catch (errData) {
      addToast(errData.message, "error")
    }
  }

  const purgeDlq = async () => {
    if (!window.confirm("Permanently remove all DLQ tasks? This cannot be undone.")) return
    try {
      const res = await fetch(`${API_URL}/dlq/purge`, {
        method: "POST",
        credentials: "include",
      })
      if (!res.ok) throw new Error("Failed to purge DLQ")
      setDlqTasks([])
      addToast("DLQ purged", "info")
    } catch (errData) {
      addToast(errData.message, "error")
    }
  }

  const fetchAdminStats = async () => {
    try {
      const res = await fetch(`${API_URL}/admin/stats`, {
        credentials: "include",
      })
      if (res.status === 403) {
        setIsAdmin(false)
        return
      }
      if (!res.ok) throw new Error("Failed to fetch admin stats")
      setIsAdmin(true)
      setAdminStats(await res.json())
    }
    catch (errData) {
      setIsAdmin(false)
    }
  }

  const fetchAdminTenants = async () => {
    try {
      const res = await fetch(`${API_URL}/admin/tenants`, {
        credentials: "include",
      })
      if (!res.ok) throw new Error("Failed to fetch tenants")
      setAdminTenants(await res.json())
    }
    catch (errData) {
      addToast(errData.message, "error")
    }
  }

  const fetchAdminTasks = async () => {
    try {
      const res = await fetch(`${API_URL}/admin/tasks?page_size=50`, {
        credentials: "include",
      })
      if (!res.ok) throw new Error("Failed to fetch all tasks")
      const data = await res.json()
      setAdminTasks(data.tasks)
    }
    catch (errData) {
      addToast(errData.message, "error")
    }
  }

  const toggleTenant = async (tenantId) => {
    try {
      const res = await fetch(`${API_URL}/admin/tenants/${tenantId}/toggle`, {
        method: "POST",
        credentials: "include",
      })
      if (!res.ok) throw new Error("Failed to toggle tenant")
      const data = await res.json()
      addToast(data.message, "info")
      fetchAdminTenants()
    }
    catch (errData) {
      addToast(errData.message, "error")
    }
  }


  useEffect(() => {
    if (!loggedIn) return

    const wsURL = API_URL.replace("http", "ws") + "/ws/tasks"
    let ws = null
    let reconnectTimer = null

    const connectWebSocket = () => {
      if (ws && ws.readyState === WebSocket.OPEN) return // Already connected  

      ws = new WebSocket(wsURL)

      // Creates the connection. unlike the fetch calls, this connection will persist and be reused for real-time updates until the user logs out or the connection drops. 
      ws.onopen = () => {
        console.log("WebSocket connected")
      }

      // Handle incoming messages - these are sent by the server whenever a task changes status, so we can update the UI in real-time without waiting for the next poll
      ws.onmessage = (event) => {
        const data = JSON.parse(event.data)
        console.log("WebSocket message received:", data.task_name, data.status)

        // Update the specific task
        setTasks(prev => {
          const updated = prev.map(t =>
            t.id === data.task_id ? { ...t, status: data.status } : t
          )
          return updated
        })
      }

      // if the connection drops, try to reconnect every 3 seconds. Without this, any dropped connection would require a manual page refresh to get real-time updates again
      ws.onclose = () => {
        console.log("WebSocket disconnected, reconnecting in 3s...")
        reconnectTimer = setTimeout(connectWebSocket, 3000)
      }

      ws.onerror = (err) => {
        console.error("WebSocket error:", err)
        ws.close()
      }
    }

    connectWebSocket()

    // Cleanup on unmount or when loggedIn changes
    return () => {
      if (ws) ws.close()
      if (reconnectTimer) clearTimeout(reconnectTimer)
    }
  }, [loggedIn])

  useEffect(() => {
    if(isAdmin){
      // For admin users, calculate stats from the full list of tasks across all tenants
      if (adminStats) {
        const breakdown = adminStats.status_breakdown || {}
        setStats({
          total: adminStats.total_tasks || 0,
          queued: breakdown.queued || 0,
          running: breakdown.running || 0,
          completed: breakdown.completed || 0,
          failed: breakdown.failed || 0,
          retrying: breakdown.retrying || 0,
          dead: breakdown.dead || 0,
        })
      }
    }
    
    else {
    // Calculate stats from tasks fetched for the logged-in tenant
    const newStats = { total: totalTasks, queued: 0, running: 0, completed: 0, failed: 0, retrying: 0, dead: 0 }
    tasks.forEach(t => {
      if (newStats[t.status] !== undefined) newStats[t.status]++
    })
    setStats(newStats)}
  }, [tasks, totalTasks, isAdmin, adminStats])


  // If no API key, show login screen
  if (!loggedIn) {
    return (
      <div className="dashboard">
        <div className="login-screen">
          <h1 className="logo" style={{ fontSize: 36, marginBottom: 8 }}>
            <span className="logo-blue">Queue</span>Flow
          </h1>
          <p className="subtitle">Distributed Task Queue Dashboard</p>
          {step === 'choose' && (
            <div className="login-form" style={{ flexDirection: "column", marginTop: 24 }}>
              <button onClick={() => setStep("new")} className="btn-primary" style={{ width: 260 }}>
                Create New Tenant
              </button>
              <button onClick={() => setStep("existing")} className="btn-secondary" style={{ width: 260 }}>
                I have an API Key
              </button>
            </div>
          )}

          {step === "new" && !createdKey && (
            <div className="login-form" style={{ flexDirection: "column", marginTop: 24 }}>
              <input
                type="text"
                placeholder="Tenant name (e.g. My Company)"
                value={tenantNameInput}
                onChange={e => setTenantNameInput(e.target.value)}
                onKeyDown={e => e.key === "Enter" && createTenant()}
                className="input"
                style={{ width: 300 }}
              />
              <button onClick={createTenant} disabled={loading} className="btn-primary" style={{ width: 300 }}>
                {loading ? "Creating..." : "Create Tenant and Connect"}
              </button>
              <button onClick={() => setStep("choose")} className="btn-ghost">
                ← Back
              </button>
            </div>
          )}

          {createdKey && (
            <div className="login-form" style={{ flexDirection: "column", marginTop: 24 }}>
              <p style={{ color: "#34d399", fontWeight: 600 }}>Tenant and its API Key created successfully!</p>
              <label className="field-label">Your API Key (save this - you won't see it again)</label>
              <div style={{ display: "flex", gap: 8 }}>
                <input
                  type="text"
                  value={createdKey}
                  readOnly
                  className="input"
                  style={{ width: 300 }}
                />
                <button
                  onClick={() => copyToClipboard(createdKey)}
                  className="btn-secondary"
                >
                  Copy
                </button>
              </div>
              <button onClick={continueAfterCreate} className="btn-primary" style={{ width: 300, marginTop: 8 }}>
                Continue to Dashboard
              </button>
            </div>
          )}

          {step === "existing" && (
            <div className="login-form" style={{ flexDirection: "column", marginTop: 24 }}>
              <input
                type="text"
                placeholder="Paste your API key here"
                value={keyInput}
                onChange={e => setKeyInput(e.target.value)}
                onKeyDown={e => e.key === "Enter" && saveKey()}
                className="input"
                style={{ width: 300 }}
              />
              <button onClick={saveKey} className="btn-primary" style={{ width: 300 }}>
                Connect
              </button>
              <button onClick={() => setStep("choose")} className="btn-ghost">
                ← Back
              </button>
            </div>
          )}

          {error && <p className="error-msg">{error}</p>}
        </div>
      </div>
    )
  }


  const statCards = [
    { label: "Total Tasks", value: stats.total, color: "#a1a6ad", filterKey: null },
    { label: "Queued Tasks", value: stats.queued, color: "#60a5fa", filterKey: "queued" },
    { label: "Running Tasks", value: stats.running, color: "#fbbf24", filterKey: "running" },
    { label: "Completed Tasks", value: stats.completed, color: "#34d399", filterKey: "completed" },
    { label: "Failed Tasks", value: stats.failed, color: "#f87171", filterKey: "failed" },
    { label: "Retrying Tasks", value: stats.retrying, color: "#c084fc", filterKey: "retrying" },
    { label: "Dead Tasks", value: stats.dead, color: "#ef4444", filterKey: "dead" },
  ]

  return (
    <div className="dashboard">
      <header className="header">
        <div className="header-left">
          <h1 className="logo">
            <span className="logo-blue">Queue</span>Flow
          </h1>
          <p className='subtitle'> Distributed Task Queue Dashboard</p>
        </div>
        <div className="header-right">
          <span style={{ color: "#94a3b8", fontSize: 13, fontWeight: 600 }}>{tenantName}</span>
          <button onClick={logout} className="btn-ghost">Logout</button>
        </div>

      </header>

      <div className="stats-grid">
        {statCards.map(card => (
          <div
            key={card.label}
            className={`stat-card ${statusFilter === card.filterKey ? "stat-card-active" : ""}`}
            onClick={() => {
              setStatusFilter(statusFilter === card.filterKey ? null : card.filterKey)
              setPage(1)
            }}
            style={{ cursor: "pointer" }}
          >
            <div className="stat-label">{card.label}</div>
            <div className="stat-value" style={{ color: card.color }}>{card.value}</div>
          </div>
        ))}
      </div>

      <main className="content">

        <div className="tabs">
          <button
            className={`tab ${activeTab === "tasks" ? "tab-active" : ""}`}
            onClick={() => setActiveTab("tasks")}
          >
            Tasks
          </button>
          <button
            className={`tab ${activeTab === "dlq" ? "tab-active" : ""}`}
            onClick={() => { setActiveTab("dlq"); fetchDlq(); }}
          >
            Dead Letter Queue
          </button>
          {isAdmin && (
            <button
              className={`tab ${activeTab === "admin" ? "tab-active" : ""}`}
              onClick={() => { setActiveTab("admin"); fetchAdminTenants(); fetchAdminTasks(); fetchAdminStats(); }}
            >
              Admin
            </button>
          )}
        </div>

        {activeTab === "tasks" && (
          <>
            {/* Submit button */}
            <button onClick={() => setShowSubmit(true)} className="btn-primary" style={{ marginBottom: 16 }}>
              + Submit Task
            </button>

            <div className="table-container">
              <table className="task-table">
                <thead>
                  <tr>
                    <th>Task ID</th>
                    <th>Name</th>
                    <th>Status</th>
                    <th>Priority</th>
                    <th>Retries</th>
                    <th>Created</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {tasks.length === 0 && (
                    <tr>
                      <td colSpan={7} className="empty-row">
                        {statusFilter
                          ? `No ${statusFilter} tasks found`
                          : "No tasks yet - submit a task to get started"}
                      </td>
                    </tr>
                  )}
                  {tasks
                    .filter(task => !statusFilter || task.status === statusFilter)
                    .map(task => (
                      <tr key={task.id} className="task-row">
                        <td className="mono">{task.id?.substring(0, 8)}</td>
                        <td className="task-name">{task.task_name}</td>
                        <td><StatusBadge status={task.status} /></td>
                        <td><PriorityBadge priority={task.priority} /></td>
                        <td className="mono">{task.retry_count}/{task.max_retries}</td>
                        <td className="time-cell">
                          {new Date(task.created_at).toLocaleString()}
                        </td>
                        <td>
                          {(task.status === "pending" || task.status === "queued") && (
                            <button onClick={() => cancelTask(task.id)} className="btn-cancel">Cancel</button>
                          )}
                          {(task.status === "failed" || task.status === "dead") && (
                            <button onClick={() => retryTask(task.id)} className="btn-retry">Retry</button>
                          )}
                          {task.status === "completed" && task.task_name === "generate_report" && (
                            <button onClick={() => downloadReport(task.id)} className="btn-retry">Download</button>
                          )}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
            {totalTasks > pageSize && (
              <div className="pagination" >
                <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1} className="btn-ghost"
                >
                  ← Previous
                </button>
                <span className="page-info">
                  Page {page} of {Math.ceil(totalTasks / pageSize)}
                </span>

                <button onClick={() => setPage(p => Math.min(Math.ceil(totalTasks / pageSize), p + 1))}
                  disabled={page >= Math.ceil(totalTasks / pageSize)}
                  className="btn-ghost">
                  Next →
                </button>
              </div>
            )}
          </>
        )}

        {activeTab === "dlq" && (
          <>
            <div style={{ display: "flex", gap: 10, marginBottom: 16 }}>
              <button onClick={retryAllDlq} className="btn-primary" disabled={dlqTasks.length === 0}>
                Retry All
              </button>
              <button onClick={purgeDlq} className="btn-cancel" disabled={dlqTasks.length === 0}>
                Purge All
              </button>
            </div>

            <div className="table-container">
              <table className="task-table">
                <thead>
                  <tr>
                    <th>Task ID</th>
                    <th>Name</th>
                    <th>Error</th>
                    <th>Retries</th>
                    <th>Failed At</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {dlqTasks.length === 0 && (
                    <tr>
                      <td colSpan={6} className="empty-row">
                        DLQ is empty — no dead tasks
                      </td>
                    </tr>
                  )}
                  {dlqTasks.map(task => (
                    <tr key={task.id} className="task-row">
                      <td className="mono">{task.id?.substring(0, 8)}</td>
                      <td className="task-name">{task.task_name}</td>
                      <td className="error-cell" title={task.error_message || ""} >
                        {task.error_message || "No error message"}
                      </td>
                      <td className="mono">{task.retry_count}/{task.max_retries}</td>
                      <td className="time-cell">
                        {task.updated_at ? new Date(task.updated_at).toLocaleString() : "N/A"}
                      </td>
                      <td>
                        <button onClick={() => retryTask(task.id)} className="btn-retry">
                          Retry
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}


        {activeTab == "admin" && isAdmin && (
          <>
            {adminStats && (
              <div className="admin-stats">
                <div className="stat-card">
                  <div className="stat-label">Total Tenants</div>
                  <div className="stat-value">{adminStats.total_tenants}</div>
                </div>
                <div className="stat-card">
                  <div className="stat-label">Total Tasks</div>
                  <div className="stat-value">{adminStats.total_tasks}</div>
                </div>
              </div>
            )}
            <h3 className="section-title" style={{ marginTop: 20 }}>All Tenants</h3>
            <div className="table-container" style={{ marginBottom: 24 }}>
              <table className="task-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Status</th>
                    <th>Tasks</th>
                    <th>API Keys</th>
                    <th>Created</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {adminTenants.map(t => (
                    <tr key={t.id} className="task-row">
                      <td className="task-name">
                        {t.name}
                        {t.is_admin && <span style={{ color: "#fbbf24", marginLeft: 8, fontSize: 11 }}>ADMIN</span>}
                      </td>
                      <td>
                        <span className="status-badge" style={{
                          color: t.is_active ? "#34d399" : "#f87171",
                          background: t.is_active ? "#34d39915" : "#f8717115",
                          border: `1px solid ${t.is_active ? "#34d39933" : "#f8717133"}`,
                        }}>
                          {t.is_active ? "ACTIVE" : "INACTIVE"}
                        </span>
                      </td>
                      <td className="mono">{t.task_count}</td>
                      <td className="mono">{t.api_key_count}</td>
                      <td className="time-cell">{new Date(t.created_at).toLocaleString()}</td>
                      <td>
                        {!t.is_admin && (
                          <button
                            onClick={() => toggleTenant(t.id)}
                            className={t.is_active ? "btn-cancel" : "btn-retry"}
                          >
                            {t.is_active ? "Deactivate" : "Activate"}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <h3 className="section-title">All Tasks (System-wide)</h3>
            <div className="table-container">
              <table className="task-table">
                <thead>
                  <tr>
                    <th>Task ID</th>
                    <th>Name</th>
                    <th>Status</th>
                    <th>Priority</th>
                    <th>Tenant</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {adminTasks.map(t => (
                    <tr key={t.id} className="task-row">
                      <td className="mono">{t.id.substring(0, 8)}</td>
                      <td className="task-name">{t.task_name}</td>
                      <td><StatusBadge status={t.status} /></td>
                      <td><PriorityBadge priority={t.priority} /></td>
                      <td className="mono">{t.tenant_id?.substring(0, 8) || "N/A"}</td>
                      <td className="time-cell">{new Date(t.created_at).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )

        }


        {/* Submit Modal */}
        {showSubmit && (
          <div className="modal-overlay" onClick={() => setShowSubmit(false)}>
            <div className="modal" onClick={e => e.stopPropagation()}>
              <h2 className="modal-title">Submit New Task</h2>

              <label className="field-label">Task Type</label>
              <select
                value={submitForm.task_name}
                onChange={e => setSubmitForm({ ...submitForm, task_name: e.target.value })}
                className="input">
                <option value="send_email">Send Email</option>
                <option value="process_image">Process Image</option>
                <option value="generate_report">Generate Report</option>
              </select>

              {submitForm.task_name === "send_email" && (
                <>
                  <label className="field-label">To</label>
                  <input
                    type="email"
                    value={submitForm.to}
                    onChange={e => setSubmitForm({ ...submitForm, to: e.target.value })}
                    className="input"
                  />
                  <label className="field-label">Subject</label>
                  <input
                    type="text"
                    value={submitForm.subject}
                    onChange={e => setSubmitForm({ ...submitForm, subject: e.target.value })}
                    className="input"
                  />
                  <label className="field-label">Body</label>
                  <textarea
                    value={submitForm.email_body}
                    onChange={e => setSubmitForm({ ...submitForm, email_body: e.target.value })}
                    className="input"
                    rows={3}
                    style={{ resize: "vertical" }}
                  />
                </>
              )}

              {submitForm.task_name === "process_image" && (
                <>
                  <label className="field-label">Image URL</label>
                  <input
                    type="text"
                    value={submitForm.image_url}
                    onChange={e => setSubmitForm({ ...submitForm, image_url: e.target.value })}
                    className="input"
                  />
                  <label className="field-label">Width (px)</label>
                  <input
                    type="number"
                    value={submitForm.width}
                    onChange={e => setSubmitForm({ ...submitForm, width: e.target.value })}
                    className="input"
                  />
                  <label className="field-label">Height (px)</label>
                  <input
                    type="number"
                    value={submitForm.height}
                    onChange={e => setSubmitForm({ ...submitForm, height: e.target.value })}
                    className="input"
                  />
                </>
              )}

              {submitForm.task_name === "generate_report" && (
                <>
                  <label className="field-label">Report Type</label>
                  <select
                    value={submitForm.report_type}
                    onChange={e => setSubmitForm({ ...submitForm, report_type: e.target.value })}
                    className="input"
                  >
                    <option value="summary">Summary</option>
                    <option value="detailed">Detailed</option>
                    <option value="monthly">Monthly</option>
                  </select>
                </>
              )}

              <label className="field-label">Priority</label>
              <select
                value={submitForm.priority}
                onChange={e => setSubmitForm({ ...submitForm, priority: parseInt(e.target.value) })}
                className="input">
                <option value={1}>Low</option>
                <option value={5}>Medium</option>
                <option value={10}>High</option>
                <option value={20}>Critical</option>
              </select>

              <label className="field-label">Delay (seconds)</label>
              <input
                type="number"
                min="0"
                placeholder="No delay"
                value={submitForm.delay_seconds}
                onChange={e => setSubmitForm({ ...submitForm, delay_seconds: e.target.value })}
                className="input"
              />

              <label className="field-label">Max Retries</label>
              <input
                type="number"
                min="0"
                max="10"
                value={submitForm.max_retries}
                onChange={e => setSubmitForm({ ...submitForm, max_retries: parseInt(e.target.value) || 0 })}
                className="input"
              />

              <label className="field-label">Callback URL (optional)</label>
              <input
                type="text"
                placeholder="https://your-app.com/webhook/task-done"
                value={submitForm.callback_url}
                onChange={e => setSubmitForm({ ...submitForm, callback_url: e.target.value })}
                className="input"
              />

              <div className="modal-actions">
                <button onClick={() => setShowSubmit(false)} className="btn-ghost"> Cancel </button>
                <button onClick={submitTask} disabled={loading} className="btn-primary">
                  {loading ? "Submitting..." : "Submit Task"}
                </button>
              </div>
            </div>
          </div>
        )}
      </main>
      {/* Toast Notifications */}
      <div className="toast-container">
        {toasts.map(toast => (
          <div key={toast.id} className={`toast toast-${toast.type}`} >
            <span>{toast.message}</span>
            <button
              onClick={() => setToasts(prev => prev.filter(t => t.id !== toast.id))}
              className="toast-close"
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}


export default App
