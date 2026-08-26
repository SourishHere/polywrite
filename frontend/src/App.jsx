import { useState } from 'react'
import './App.css'

function App() {
  const [text, setText] = useState('')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)

  const checkGrammar = async () => {
    if (!text.trim()) return
    setLoading(true)
    try {
      const response = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      })
      if (!response.ok) throw new Error(`Backend returned ${response.status}`)
      setResult(await response.json())
    } catch (error) {
      console.error(error)
      setResult({ message: 'Could not connect to backend' })
    } finally {
      setLoading(false)
    }
  }

  const clearResult = () => setResult(null)
  const counts = result?.counts || { grammar: 0, spelling: 0, clarity: 0 }

  return (
    <div className="app">
      <header className="navbar">
        <div className="logo">PolyWrite</div>
        <select className="language" defaultValue="English">
          <option>English</option>
          <option disabled>German — coming soon</option>
          <option disabled>Hindi — coming soon</option>
          <option disabled>Tamil — coming soon</option>
          <option disabled>Telugu — coming soon</option>
        </select>
      </header>

      <main className="main">
        <div className="editor-card">
          <div className="editor-header">
            <span>Write your text</span>
            <span>{text.trim() ? text.trim().split(/\s+/).length : 0} words</span>
          </div>
          <textarea
            value={text}
            onChange={(e) => { setText(e.target.value); if (result) clearResult() }}
            placeholder="Write or paste your text here..."
          />
          <div className="editor-footer">
            <span>{text.length} characters</span>
            <button onClick={checkGrammar} disabled={loading || !text.trim()}>
              {loading ? 'Checking...' : 'Check Grammar'}
            </button>
          </div>
        </div>

        <div className="suggestions">
          <h2>Suggestions</h2>
          {!result ? (
            <>
              <div className="suggestion-stats">
                <div><strong>Grammar</strong><span>0 issues</span></div>
                <div><strong>Spelling</strong><span>0 issues</span></div>
                <div><strong>Clarity</strong><span>—</span></div>
              </div>
              <div className="empty-state"><p>Your writing suggestions will appear here.</p></div>
            </>
          ) : result.issues ? (
            <>
              <div className="suggestion-stats">
                <div><strong>Grammar</strong><span>{counts.grammar} {counts.grammar === 1 ? 'issue' : 'issues'}</span></div>
                <div><strong>Spelling</strong><span>{counts.spelling} {counts.spelling === 1 ? 'issue' : 'issues'}</span></div>
                <div><strong>Clarity</strong><span>{counts.clarity} {counts.clarity === 1 ? 'issue' : 'issues'}</span></div>
              </div>

              <div className="empty-state">
                <p><strong>{result.message}</strong></p>
                <p><strong>Corrected text:</strong> {result.corrected_text}</p>
              </div>

              {result.issues.length === 0 ? (
                <div className="empty-state"><p>✓ Your text looks good!</p></div>
              ) : (
                <div className="issue-list">
                  {result.issues.map((issue, index) => (
                    <div className="issue" key={`${issue.original}-${index}`}>
                      <span className="issue-type">{issue.type}</span>
                      <p><strong>{issue.original}</strong> → <strong>{issue.suggestion}</strong></p>
                      <small>{issue.explanation}</small>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : (
            <div className="empty-state"><p>{result.message}</p></div>
          )}
        </div>
      </main>
    </div>
  )
}

export default App
