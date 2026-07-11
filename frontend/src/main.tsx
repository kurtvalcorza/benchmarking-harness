import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Link, Route, Routes } from 'react-router-dom'
import { AdjudicationQueue } from './pages/AdjudicationQueue'
import { ModelDetail } from './pages/ModelDetail'
import { Review } from './pages/Review'
import { Submit } from './pages/Submit'
import './styles.css'

function App() {
  return (
    <BrowserRouter>
      <header className="topbar">
        <span className="brand">⚖️ Model Benchmarking Harness</span>
        <nav>
          <Link to="/">Submit</Link>
          <Link to="/adjudication">Adjudication queue</Link>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Submit />} />
          <Route path="/models/:id" element={<ModelDetail />} />
          <Route path="/adjudication" element={<AdjudicationQueue />} />
          <Route path="/adjudication/:runId" element={<Review />} />
        </Routes>
      </main>
    </BrowserRouter>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
