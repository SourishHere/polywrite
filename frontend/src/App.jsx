import { useState } from 'react'
import './App.css'

function App() {
  const [text, setText] = useState('')

  return (
    <div className="app">
      <header className="navbar">
        <div className="logo">PolyWrite</div>

        <select className="language">
          <option>English</option>
          <option>German</option>
          <option>Hindi</option>
          <option>Tamil</option>
          <option>Telugu</option>
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
            onChange={(e) => setText(e.target.value)}
            placeholder="Write or paste your text here..."
          />

          <div className="editor-footer">
            <span>{text.length} characters</span>

            <button>
              Check Grammar
            </button>
          </div>
        </div>

        <div className="suggestions">
          <h2>Suggestions</h2>

          <div className="suggestion-stats">
            <div>
              <strong>Grammar</strong>
              <span>0 issues</span>
            </div>

            <div>
              <strong>Spelling</strong>
              <span>0 issues</span>
            </div>

            <div>
              <strong>Clarity</strong>
              <span>—</span>
            </div>
          </div>

          <div className="empty-state">
            <p>Your writing suggestions will appear here.</p>
          </div>
        </div>
      </main>
    </div>
  )
}

export default App