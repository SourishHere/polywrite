import { useState } from 'react'
import './App.css'

const emptyCounts = { grammar: 0, spelling: 0, clarity: 0, total: 0 }

function App() {
  const [text, setText] = useState('')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [history, setHistory] = useState([])
  const [filter, setFilter] = useState('all')
  const [error, setError] = useState('')

  const checkGrammar = async () => {
    if (!text.trim()) return
    setLoading(true)
    setError('')
    try {
      const response = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      })
      if (!response.ok) throw new Error(`Backend returned ${response.status}`)
      setResult(await response.json())
    } catch (err) {
      console.error(err)
      setError('Could not connect to the PolyWrite backend. Make sure the API is running on port 8000.')
      setResult(null)
    } finally {
      setLoading(false)
    }
  }

  const remember = () => setHistory((h) => [...h.slice(-9), text])

  const recalculate = (issues, correctedText) => {
    const counts = { ...emptyCounts }
    issues.forEach((item) => { counts[item.type] += 1 })
    counts.total = issues.length
    return {
      issues,
      corrected_text: correctedText,
      counts,
      score: Math.max(0, 100 - counts.grammar * 8 - counts.spelling * 5 - counts.clarity * 3),
      message: issues.length ? 'Analysis complete' : 'All corrections applied',
    }
  }

  const applyCorrection = (issue) => {
    if (issue.type === 'clarity') return
    remember()
    const updated = text.replace(issue.original, issue.suggestion)
    setText(updated)
    setResult((current) => recalculate(current.issues.filter((item) => item !== issue), updated))
  }

  const applyAllCorrections = () => {
    if (!result?.issues?.length) return
    remember()
    let corrected = result.corrected_text || text
    // The backend has already produced the safest combined correction.
    setText(corrected)
    setResult((current) => recalculate(current.issues.filter((item) => item.type === 'clarity'), corrected))
  }

  const undo = () => {
    if (!history.length) return
    setText(history[history.length - 1])
    setHistory((h) => h.slice(0, -1))
    setResult(null)
  }

  const clear = () => {
    setText('')
    setResult(null)
    setHistory([])
    setError('')
    setFilter('all')
  }

  const counts = result?.counts || emptyCounts
  const visibleIssues = result?.issues?.filter((i) => filter === 'all' || i.type === filter) || []

  return (
    <div className="app">
      <header className="navbar">
        <div className="logo">PolyWrite <span>English</span></div>
        <div className="nav-actions">
          <button className="undo" onClick={undo} disabled={!history.length}>↶ Undo</button>
          <select className="language" defaultValue="English">
            <option>English</option>
            <option disabled>German — coming soon</option>
            <option disabled>Hindi — coming soon</option>
            <option disabled>Tamil — coming soon</option>
            <option disabled>Telugu — coming soon</option>
          </select>
        </div>
      </header>

      <main className="main">
        <section className="hero">
          <h1>Write better. <span>Instantly.</span></h1>
          <p>Grammar, spelling and clarity suggestions for English.</p>
        </section>

        <div className="editor-card">
          <div className="editor-header">
            <span>Write your text</span>
            <span>{text.trim() ? text.trim().split(/\s+/).length : 0} words</span>
          </div>
          <textarea
            value={text}
            onChange={(e) => { setText(e.target.value); setResult(null); setError('') }}
            placeholder="Write or paste your English text here..."
          />
          <div className="editor-footer">
            <span>{text.length} characters</span>
            <div>
              <button className="secondary" onClick={clear} disabled={!text}>Clear</button>
              <button onClick={checkGrammar} disabled={loading || !text.trim()}>{loading ? 'Checking...' : 'Check Grammar'}</button>
            </div>
          </div>
        </div>

        {error && <div className="empty-state"><p>{error}</p></div>}

        <section className="suggestions">
          <div className="suggestions-title">
            <div><h2>Suggestions</h2><p className="sub">Review and apply corrections.</p></div>
            {result?.issues?.some((i) => i.type !== 'clarity') && <button className="apply-all" onClick={applyAllCorrections}>Apply All</button>}
          </div>

          {result?.score !== undefined && (
            <div className="score-row">
              <div className="score"><strong>{result.score}</strong><span>/100</span></div>
              <div className="score-copy"><b>Writing Score</b><p>{result.score >= 90 ? 'Excellent writing' : result.score >= 75 ? 'Good writing — a few improvements' : 'Room for improvement'}</p></div>
              <div className="stat"><b>{result.stats.words}</b><span>Words</span></div>
              <div className="stat"><b>{result.stats.sentences}</b><span>Sentences</span></div>
              <div className="stat"><b>{result.stats.characters}</b><span>Characters</span></div>
            </div>
          )}

          {!result ? (
            <div className="suggestion-stats"><div><strong>Grammar</strong><span>0 issues</span></div><div><strong>Spelling</strong><span>0 issues</span></div><div><strong>Clarity</strong><span>—</span></div></div>
          ) : (
            <>
              <div className="suggestion-stats">
                <button className={filter === 'all' ? 'active-filter' : ''} onClick={() => setFilter('all')}><strong>All</strong><span>{counts.total} issues</span></button>
                <button className={filter === 'grammar' ? 'active-filter' : ''} onClick={() => setFilter('grammar')}><strong>Grammar</strong><span>{counts.grammar} issues</span></button>
                <button className={filter === 'spelling' ? 'active-filter' : ''} onClick={() => setFilter('spelling')}><strong>Spelling</strong><span>{counts.spelling} issues</span></button>
                <button className={filter === 'clarity' ? 'active-filter' : ''} onClick={() => setFilter('clarity')}><strong>Clarity</strong><span>{counts.clarity} issues</span></button>
              </div>

              {visibleIssues.length ? (
                <div className="issue-list">
                  {visibleIssues.map((issue, index) => (
                    <div className={`issue issue-${issue.type}`} key={`${issue.original}-${issue.suggestion}-${index}`}>
                      <div className="issue-top"><span className="issue-type">{issue.type}</span>{issue.type !== 'clarity' && <button className="apply-button" onClick={() => applyCorrection(issue)}>Apply</button>}</div>
                      <p><strong>{issue.original}</strong><span className="arrow">→</span><strong>{issue.suggestion}</strong></p>
                      <small>{issue.explanation}</small>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="empty-state success-state"><div className="success-icon">✓</div><h3>{result.message || 'No issues found'}</h3><p>Your English looks good!</p></div>
              )}

              <div className="corrected-box">
                <div className="corrected-header"><strong>Corrected version</strong><button className="copy" onClick={() => navigator.clipboard?.writeText(result.corrected_text || '')}>Copy</button></div>
                <p>{result.corrected_text || result.text}</p>
              </div>
            </>
          )}
        </section>
      </main>
    </div>
  )
}

export default App
