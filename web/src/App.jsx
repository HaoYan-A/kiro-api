import { useState, useEffect } from 'react'
import './App.css'

// API base URL
const API_BASE = '/admin'

// Basic Auth credentials storage
function getAuthHeader() {
  const credentials = localStorage.getItem('credentials')
  if (credentials) {
    return `Basic ${btoa(credentials)}`
  }
  return null
}

function setCredentials(username, password) {
  localStorage.setItem('credentials', `${username}:${password}`)
}

function clearCredentials() {
  localStorage.removeItem('credentials')
}

// API helper
async function api(endpoint, options = {}) {
  const authHeader = getAuthHeader()
  const headers = {
    'Content-Type': 'application/json',
    ...options.headers,
  }
  if (authHeader) {
    headers['Authorization'] = authHeader
  }

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  })

  if (response.status === 401) {
    clearCredentials()
    throw new Error('Unauthorized')
  }

  return response
}

// Login Component
function Login({ onLogin }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError('')

    try {
      setCredentials(username, password)
      const response = await api('/check-auth')
      if (response.ok) {
        onLogin()
      } else {
        clearCredentials()
        setError('Invalid credentials')
      }
    } catch (err) {
      clearCredentials()
      setError('Invalid credentials')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-container">
      <h1>Kiro API Admin</h1>
      <form onSubmit={handleSubmit} className="login-form">
        <input
          type="text"
          placeholder="Username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          required
        />
        <input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        {error && <div className="error">{error}</div>}
        <button type="submit" disabled={loading}>
          {loading ? 'Logging in...' : 'Login'}
        </button>
      </form>
    </div>
  )
}

// Account List Component
function AccountList({ onEdit, onRefresh }) {
  const [accounts, setAccounts] = useState([])
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState({})

  const loadAccounts = async () => {
    try {
      const response = await api('/accounts')
      if (response.ok) {
        const data = await response.json()
        setAccounts(data)
      }
    } catch (err) {
      console.error('Failed to load accounts:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadAccounts()
  }, [])

  const handleToggle = async (name) => {
    setActionLoading({ ...actionLoading, [name]: 'toggle' })
    try {
      const response = await api(`/accounts/${name}/toggle`, { method: 'POST' })
      if (response.ok) {
        await loadAccounts()
      }
    } finally {
      setActionLoading({ ...actionLoading, [name]: null })
    }
  }

  const handleDelete = async (name) => {
    if (!confirm(`Delete account "${name}"?`)) return
    setActionLoading({ ...actionLoading, [name]: 'delete' })
    try {
      const response = await api(`/accounts/${name}`, { method: 'DELETE' })
      if (response.ok) {
        await loadAccounts()
      }
    } finally {
      setActionLoading({ ...actionLoading, [name]: null })
    }
  }

  const handleRefresh = async (name) => {
    setActionLoading({ ...actionLoading, [name]: 'refresh' })
    try {
      const response = await api(`/accounts/${name}/refresh`, { method: 'POST' })
      const data = await response.json()
      if (data.success) {
        alert('Token refreshed successfully')
        await loadAccounts()
      } else {
        alert(`Refresh failed: ${data.message}`)
      }
    } catch (err) {
      alert(`Refresh failed: ${err.message}`)
    } finally {
      setActionLoading({ ...actionLoading, [name]: null })
    }
  }

  const handleTest = async (name) => {
    setActionLoading({ ...actionLoading, [name]: 'test' })
    try {
      const response = await api(`/accounts/${name}/test`, { method: 'POST' })
      const data = await response.json()
      if (data.success) {
        const result = data.data || {}
        alert(
          `Test successful!\n\n` +
          `Profiles: ${result.profiles?.join(', ') || 'N/A'}\n` +
          `Model: ${result.model || 'N/A'}\n\n` +
          `AI Response:\n${result.ai_response || 'N/A'}`
        )
      } else {
        alert(`Test failed: ${data.message}`)
      }
    } catch (err) {
      alert(`Test failed: ${err.message}`)
    } finally {
      setActionLoading({ ...actionLoading, [name]: null })
    }
  }

  if (loading) {
    return <div className="loading">Loading...</div>
  }

  return (
    <div className="account-list">
      <div className="list-header">
        <h2>Accounts</h2>
        <button onClick={onRefresh} className="btn-primary">
          + Add Account
        </button>
      </div>

      {accounts.length === 0 ? (
        <div className="empty">No accounts configured</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>API Key</th>
              <th>Status</th>
              <th>Token Expires</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {accounts.map((account) => (
              <tr key={account.name} className={!account.enabled ? 'disabled' : ''}>
                <td>{account.name}</td>
                <td className="api-key">{account.api_key}</td>
                <td>
                  <span className={`status ${account.enabled ? 'active' : 'inactive'}`}>
                    {account.enabled ? 'Active' : 'Disabled'}
                  </span>
                  {account.has_token && (
                    <span className={`token-status ${account.is_expired ? 'expired' : 'valid'}`}>
                      {account.is_expired ? 'Expired' : 'Valid'}
                    </span>
                  )}
                </td>
                <td>{account.expires_at || '-'}</td>
                <td className="actions">
                  <button
                    onClick={() => onEdit(account)}
                    disabled={actionLoading[account.name]}
                  >
                    Edit
                  </button>
                  <button
                    onClick={() => handleToggle(account.name)}
                    disabled={actionLoading[account.name]}
                  >
                    {account.enabled ? 'Disable' : 'Enable'}
                  </button>
                  <button
                    onClick={() => handleTest(account.name)}
                    disabled={actionLoading[account.name]}
                    className="btn-test"
                  >
                    {actionLoading[account.name] === 'test' ? '...' : 'Test'}
                  </button>
                  <button
                    onClick={() => handleRefresh(account.name)}
                    disabled={actionLoading[account.name] || !account.has_token}
                    className="btn-refresh"
                  >
                    {actionLoading[account.name] === 'refresh' ? '...' : 'Refresh'}
                  </button>
                  <button
                    onClick={() => handleDelete(account.name)}
                    disabled={actionLoading[account.name]}
                    className="btn-danger"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

// File Drop Zone Component
function FileDropZone({ label, hint, onFileParsed, preview }) {
  const [dragging, setDragging] = useState(false)

  const handleFile = (file) => {
    if (!file) return
    const reader = new FileReader()
    reader.onload = (event) => {
      try {
        const data = JSON.parse(event.target.result)
        onFileParsed(data)
      } catch (err) {
        onFileParsed(null, 'Failed to parse JSON file')
      }
    }
    reader.readAsText(file)
  }

  const handleDrop = (e) => {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    handleFile(file)
  }

  const handleDragOver = (e) => {
    e.preventDefault()
    setDragging(true)
  }

  const handleDragLeave = () => {
    setDragging(false)
  }

  const handleClick = () => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.json'
    input.onchange = (e) => handleFile(e.target.files[0])
    input.click()
  }

  return (
    <div className="form-group">
      <label>{label}</label>
      <p className="hint">{hint}</p>
      <div
        className={`drop-zone ${dragging ? 'dragging' : ''} ${preview ? 'has-file' : ''}`}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onClick={handleClick}
      >
        {preview ? (
          <div className="file-preview">{preview}</div>
        ) : (
          <div className="drop-placeholder">
            Drop JSON file here or click to select
          </div>
        )}
      </div>
    </div>
  )
}

// Account Form Component
function AccountForm({ account, onSave, onCancel }) {
  const [name, setName] = useState(account?.name || '')
  const [apiKey, setApiKey] = useState(account?.api_key || '')
  const [tokenData, setTokenData] = useState(null)
  const [clientData, setClientData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const isEdit = !!account

  const handleTokenParsed = (data, err) => {
    if (err) {
      setError(err)
      return
    }
    setTokenData({
      accessToken: data.accessToken,
      refreshToken: data.refreshToken,
      expiresAt: data.expiresAt,
      clientIdHash: data.clientIdHash,
    })
    setError('')
  }

  const handleClientParsed = (data, err) => {
    if (err) {
      setError(err)
      return
    }
    setClientData({
      clientId: data.clientId,
      clientSecret: data.clientSecret,
    })
    setError('')
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError('')

    try {
      if (isEdit) {
        const response = await api(`/accounts/${account.name}`, {
          method: 'PUT',
          body: JSON.stringify({ api_key: apiKey }),
        })
        if (!response.ok) {
          throw new Error('Failed to update account')
        }
      } else {
        const response = await api('/accounts', {
          method: 'POST',
          body: JSON.stringify({ name, api_key: apiKey || null }),
        })
        if (!response.ok) {
          const data = await response.json()
          throw new Error(data.detail || 'Failed to create account')
        }
      }

      // Save token if both files provided
      if (tokenData && clientData) {
        const tokenResponse = await api(`/accounts/${isEdit ? account.name : name}/token`, {
          method: 'POST',
          body: JSON.stringify({
            access_token: tokenData.accessToken,
            refresh_token: tokenData.refreshToken,
            expires_at: tokenData.expiresAt,
            client_id_hash: tokenData.clientIdHash,
            client_id: clientData.clientId,
            client_secret: clientData.clientSecret,
          }),
        })
        if (!tokenResponse.ok) {
          throw new Error('Failed to save token')
        }
      }

      onSave()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="account-form">
      <h2>{isEdit ? 'Edit Account' : 'Add Account'}</h2>
      <form onSubmit={handleSubmit}>
        <div className="form-group">
          <label>Account Name</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={isEdit}
            required
            placeholder="e.g., my-account"
          />
        </div>

        <div className="form-group">
          <label>API Key (leave empty to auto-generate)</label>
          <input
            type="text"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="sk-kiro-..."
          />
        </div>

        <h3>Upload Token Files</h3>

        <FileDropZone
          label="1. kiro-auth-token.json"
          hint="~/.aws/sso/cache/kiro-auth-token.json"
          onFileParsed={handleTokenParsed}
          preview={tokenData && (
            <>
              <div className="preview-item"><strong>Access Token:</strong> {tokenData.accessToken?.substring(0, 30)}...</div>
              <div className="preview-item"><strong>Refresh Token:</strong> {tokenData.refreshToken?.substring(0, 30)}...</div>
              <div className="preview-item"><strong>Expires At:</strong> {tokenData.expiresAt}</div>
              <div className="preview-item"><strong>Client ID Hash:</strong> {tokenData.clientIdHash}</div>
            </>
          )}
        />

        <FileDropZone
          label="2. Client Credentials"
          hint={`~/.aws/sso/cache/${tokenData?.clientIdHash || '[clientIdHash]'}.json`}
          onFileParsed={handleClientParsed}
          preview={clientData && (
            <>
              <div className="preview-item"><strong>Client ID:</strong> {clientData.clientId}</div>
              <div className="preview-item"><strong>Client Secret:</strong> {clientData.clientSecret?.substring(0, 50)}...</div>
            </>
          )}
        />

        {error && <div className="error">{error}</div>}

        <div className="form-actions">
          <button type="button" onClick={onCancel}>
            Cancel
          </button>
          <button type="submit" disabled={loading} className="btn-primary">
            {loading ? 'Saving...' : 'Save'}
          </button>
        </div>
      </form>
    </div>
  )
}

// Main App Component
function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(false)
  const [view, setView] = useState('list') // 'list' | 'form'
  const [editAccount, setEditAccount] = useState(null)
  const [checkingAuth, setCheckingAuth] = useState(true)

  // Check if already logged in
  useEffect(() => {
    const checkAuth = async () => {
      if (getAuthHeader()) {
        try {
          const response = await api('/check-auth')
          if (response.ok) {
            setIsLoggedIn(true)
          }
        } catch {
          clearCredentials()
        }
      }
      setCheckingAuth(false)
    }
    checkAuth()
  }, [])

  const handleLogout = () => {
    clearCredentials()
    setIsLoggedIn(false)
  }

  const handleEdit = (account) => {
    setEditAccount(account)
    setView('form')
  }

  const handleAdd = () => {
    setEditAccount(null)
    setView('form')
  }

  const handleSave = () => {
    setEditAccount(null)
    setView('list')
  }

  const handleCancel = () => {
    setEditAccount(null)
    setView('list')
  }

  if (checkingAuth) {
    return <div className="loading">Loading...</div>
  }

  if (!isLoggedIn) {
    return <Login onLogin={() => setIsLoggedIn(true)} />
  }

  return (
    <div className="app">
      <header>
        <h1>Kiro API Admin</h1>
        <button onClick={handleLogout} className="btn-logout">
          Logout
        </button>
      </header>

      <main>
        {view === 'list' ? (
          <AccountList onEdit={handleEdit} onRefresh={handleAdd} />
        ) : (
          <AccountForm
            account={editAccount}
            onSave={handleSave}
            onCancel={handleCancel}
          />
        )}
      </main>
    </div>
  )
}

export default App
