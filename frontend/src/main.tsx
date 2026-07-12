import React, { useState } from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Link, Navigate, Route, Routes } from 'react-router-dom'
import { SignIn } from './auth/SignIn'
import { clearToken, currentPrincipal } from './auth/session'
import { AdjudicationQueue } from './pages/AdjudicationQueue'
import { ModelDetail } from './pages/ModelDetail'
import { ModelsList } from './pages/ModelsList'
import { Review } from './pages/Review'
import { Submit } from './pages/Submit'
import './styles.css'

function App() {
  // re-render on sign-in/out by bumping a token
  const [, setTick] = useState(0)
  const refresh = () => setTick((n) => n + 1)
  const principal = currentPrincipal()

  if (!principal) return <SignIn onSignedIn={refresh} />

  const canSubmit = principal.roles.includes('submitter')
  const canAdjudicate =
    principal.roles.includes('adjudicator') || principal.roles.includes('auditor')
  // GET /models is object-scoped: auditor→all, submitter→own, adjudicator→flagged
  // (governance holds no arbitrary model read, so it gets an empty list).
  const canListModels =
    principal.roles.includes('auditor') ||
    principal.roles.includes('submitter') ||
    principal.roles.includes('adjudicator')

  function signOut() {
    clearToken()
    refresh()
  }

  return (
    <BrowserRouter>
      <header className="topbar">
        <span className="brand">⚖️ Model Benchmarking Harness</span>
        <nav>
          {canSubmit && <Link to="/">Submit</Link>}
          {canListModels && <Link to="/models">Models</Link>}
          {canAdjudicate && <Link to="/adjudication">Adjudication queue</Link>}
        </nav>
        <span className="identity">
          {principal.subject} · [{principal.roles.join(', ') || 'no roles'}]{' '}
          <button className="link" onClick={signOut}>
            sign out
          </button>
        </span>
      </header>
      <main>
        <Routes>
          <Route
            path="/"
            element={canSubmit ? <Submit /> : <Forbidden action="submit models" />}
          />
          <Route
            path="/models"
            element={canListModels ? <ModelsList /> : <Forbidden action="list models" />}
          />
          <Route path="/models/:id" element={<ModelDetail />} />
          <Route
            path="/adjudication"
            element={
              canAdjudicate ? <AdjudicationQueue /> : <Forbidden action="read the queue" />
            }
          />
          <Route
            path="/adjudication/:runId"
            element={
              principal.roles.includes('adjudicator') ? (
                <Review />
              ) : (
                <Forbidden action="record decisions" />
              )
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </BrowserRouter>
  )
}

function Forbidden({ action }: { action: string }) {
  return (
    <p className="error">
      Your signed-in identity is not authorized to {action}. Sign in with a token
      that carries the required role.
    </p>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
