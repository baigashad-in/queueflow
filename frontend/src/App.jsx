import { useState, useEffect } from 'react'
import './App.css'



function StatusBadge({status}) {
  const config = {
    pending: {color: "#94a3b8", icon: '◷'},
    queued: {color: "#60a5fa", icon: '⏳'},
    running: {color: "#fbbf24", icon: '▶'},
    completed: {color: "#34d399", icon: '✓'},
    failed: {color: "#f87171", icon: '✗'},
    retrying: {color: "#c084fc", icon: '⟳'},
    dead: {color: "#ef4444", icon: '☠'},
  }
  const cfg = config[status] || config.pending

return(
  <span className = "status-badge" style = {{
    color: cfg.color,
    background: `${cfg.color}15`,
    border: `1px solid ${cfg.color}33`,
  }}>
    <span>{cfg.icon}</span> {status.toUpperCase()}
  </span>
)
}

function PriorityBadge({priority}) {
  const labels = {1: "LOW", 5: "MEDIUM", 10: "HIGH", 20: "CRITICAL"}
  const colors = {1: "#94a3b8", 5: "#60a5fa", 10: "#fbbf24", 20: "#ef4444"}
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

const API_URL = "http://localhost:8000"
// const API_URL = "http://20.240.221.65:8000"
// const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function App() {

  // State variables
  // const [apiKey, setApiKey] = useState(localStorage.getItem("qf_api_key") || "")
  const [tasks, setTasks] = useState([])
  const [keyInput, setKeyInput] = useState("")
  const [loggedIn, setLoggedIn] = useState(false) // New state to track login status
  const [error, setError] = useState("")
  const [step, setStep] = useState('choose')  // 'choose', 'new', 'existing'
  const [tenantName, setTenantName] = useState("")
  const [loading, setLoading] = useState(false)
  const [stats, setStats] = useState({
    total: 0, queued: 0, running: 0, completed: 0,
    failed: 0, retrying: 0, dead: 0,
  })

  const saveKey = async() => {
    if (!keyInput.trim()) return
    setLoading(true)
    setError("")
    try {
      const res = await fetch(`${API_URL}/auth/login`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        credentials: "include",
        body: JSON.stringify({api_key: keyInput.trim()}),
      })
      if (!res.ok) throw new Error("Invalid API key")
      const data = await res.json()
      setLoggedIn(true)
      setTenantName(data.tenant_name)
    }
    catch (err) {
      setError(err.message)
    }
      setLoading(false)
  }

  const logout = async () => {
    await fetch(`${API_URL}/auth/logout`, {
      method: "POST",
      credentials: "include",
    })
    setLoggedIn(false)
    setStats({
      total: 0, queued: 0, running: 0, completed: 0,
      failed: 0, retrying: 0, dead: 0,
    })
  }

  

  useEffect(() => {
    if (!loggedIn) return
    
    const fetchTasks = async () => {
      try {
        const response = await fetch(`${API_URL}/tasks/?page_size=100`, {
          credentials: "include",
        })
        if (response.status === 401) {
          setLoggedIn(false)
          setError("Session expired. Please log in again.")
          return
        }
        if (!response.ok) throw new Error("Failed to fetch tasks")
          const data = await response.json()
        setTasks(data.tasks)

        // Calculate stats from tasks
        const newStats = {total: data.total, queued: 0, running: 0, completed: 0, failed: 0, retrying: 0, dead: 0}
        data.tasks.forEach(currentTask => {
          if (newStats[currentTask.status] !== undefined) newStats[currentTask.status]++
        })
        setStats(newStats)
      }
      catch (err) {
        setError(err.message)
      }
    }

    fetchTasks()
    const interval = setInterval(fetchTasks, 5000)
    return () => clearInterval(interval)
  }, [loggedIn])

  const createTenant = async () => {
    if (!tenantName.trim()) { setError("Tenant name is required"); return }
    setLoading(true)
    try {
          const response1 = await fetch(`${API_URL}/tenants/`, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({name: tenantName.trim()}),
          })
          if (!response1.ok) throw new Error("Failed to create tenant")
          const tenant = await response1.json()
          const response2 = await fetch(`${API_URL}/tenants/${tenant.id}/api-keys/`, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({label: "dashboard"}),
          })
          if (!response2.ok) throw new Error("Failed to create API key")
          const apiKeyData = await response2.json()

          // Login with the new key(sets HTTP-only cookie)
          const response3 = await fetch(`${API_URL}/auth/login`, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            credentials: "include",
            body: JSON.stringify({api_key: apiKeyData.key}),
          })
          if (!response3.ok) throw new Error("Failed to login with new API key")
          const loginData = await response3.json()
          setLoggedIn(true)
          setTenantName(loginData.tenant_name)
        } 
    catch (err) {
          setError(err.message)
        }
      setLoading(false)
    }






  // If no API key, show login screen
  if (!loggedIn) {
    return (
      <div className = "dashboard">
        <div className = "login-screen">
          <h1 className = "logo" style = {{ fontSize: 36, marginBottom: 8}}>
            <span className = "logo-blue">Queue</span>Flow
          </h1>
          <p className = "subtitle">Distributed Task Queue Dashboard</p>
          {step === 'choose' && (
            <div className = "login-form" style={{flexDirection: "column", marginTop: 24}}>
              <button onClick = {() => setStep("new")} className = "btn-primary" style = {{width : 260}}>
                Create New Tenant 
              </button>
              <button onClick = {() => setStep("existing")} className = "btn-secondary" style = {{width : 260}}>
                I have an API Key
              </button>
            </div>
          )}

          {step === "new" && (
            <div className = "login-form" style = {{ flexDirection: "column", marginTop: 24}}>
              <input 
              type = "text"
              placeholder = "Tenant name (e.g. My Company)"
              value = {tenantName}
              onChange={e => setTenantName(e.target.value)}
              onKeyDown = {e =>e.key === "Enter" && createTenant()}
              className = "input"
              style = {{width:300}}
              />
              <button onClick = {createTenant} disabled = {loading} className = "btn-primary" style = {{width: 300}}>
                {loading ? "Creating..." : "Create Tenant and Connect"}
              </button>
              <button onClick = {() => setStep("choose")} className = "btn-ghost">
                ← Back
              </button>
            </div>
          )}

          {step === "existing" && (
            <div className = "login-form" style = {{flexDirection: "column", marginTop: 24}}>
              <input
                type = "text"
                placeholder = "Paste your API key here"
                value = {keyInput}
                onChange = {e => setKeyInput(e.target.value)}
                onKeyDown = {e => e.key === "Enter" && saveKey()}
                className = "input"
                style = {{width: 300}}
              />
              <button onClick = {saveKey} className = "btn-primary" style = {{width: 300}}>
                Connect
              </button>
              <button onClick = {() => setStep("choose")} className = "btn-ghost">
                ← Back
              </button>
            </div>
          )}

          {error && <p className = "error-msg">{error}</p>}
        </div>
      </div>
    )
  }

  
  const statCards = [
    { label: "Total Tasks", value: stats.total, color: "#e2e8f0" },
    { label: "Queued Tasks", value: stats.queued, color: "#60a5fa" },
    { label: "Running Tasks", value: stats.running, color: "#fbbf24" },
    { label: "Completed Tasks", value: stats.completed, color: "#34d399" },
    { label: "Failed Tasks", value: stats.failed, color: "#f87171" },
    { label: "Retrying Tasks", value: stats.retrying, color: "#c084fc" },
    { label: "Dead Tasks", value: stats.dead, color: "#ef4444" },
  ]

  return (
    <div className = "dashboard">
      <header className = "header">
        <div className = "header-left">
          <h1 className = "logo">
            <span className = "logo-blue">Queue</span>Flow
          </h1>
          <p className='subtitle'> Distributed Task Queue Dashboard</p>
        </div>
        <div className="header-right">
          <button onClick={logout} className = "btn-ghost">Logout</button>
        </div>
        
      </header>

      <div className = "stats-grid">
        {statCards.map(card => (
          <div key = {card.label} className = "stat-card">
            <div className="stat-label">{card.label}</div>
            <div className="stat-value" style={{color: card.color}}>{card.value}</div>
          </div>
        ))}
      </div>

      <main className = "content">
        {error && <p className = "error-msg">{error}</p>}
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
                </tr>
              </thead>
              <tbody>
                  {tasks.length === 0 && (
                    <tr>
                      <td colSpan={6} className = "empty-row">
                        No tasks yet - submit a task to get started
                      </td>
                    </tr>
                  )}
                  {tasks.map(task => (
                    <tr key = {task.id} className = "task-row">
                      <td className = "mono"> {task.id.substring(0,8)}</td>
                      <td className = "task-name">{task.task_name}</td>
                      <td><StatusBadge status = {task.status} /></td>
                      <td><PriorityBadge priority={task.priority} /></td>
                      <td className = "mono"> {task.retry_count}/{task.max_retries}</td>
                      <td className = "time-cell">
                        {new Date(task.created_at).toLocaleString()}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
        </div>
      </main>
    </div>
  )
}
 

export default App
