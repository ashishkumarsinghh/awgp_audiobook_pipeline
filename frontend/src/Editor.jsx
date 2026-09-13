import { API_BASE } from './config'
import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'

function Editor() {
  const { id: project } = useParams()
  const [segments, setSegments] = useState([])
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch(`${API_BASE}/api/projects/${project}/segments`)
      .then(async (res) => {
        if (!res.ok) throw new Error(await res.text())
        return res.json()
      })
      .then(data => setSegments(data))
      .catch(err => setError(err.message))
  }, [project])

  const runStage = async (stageNum) => {
    await fetch(`${API_BASE}/api/projects/${project}/stage/${stageNum}`, { method: 'POST' })
    alert(`Stage ${stageNum} triggered in the background! Watch the console.`)
  }

  return (
    <div style={{ padding: '20px', fontFamily: 'sans-serif' }}>
      <Link to="/">&larr; Back to Dashboard</Link>
      <h1>Editor: {project}</h1>
      
      <div style={{ marginBottom: '20px' }}>
        <button onClick={() => runStage(1)}>Run Stage 1 (Segment)</button>{' '}
        <button onClick={() => runStage(2)}>Run Stage 2 (Phonetics)</button>{' '}
        <button onClick={() => runStage(3)}>Run Stage 3 (Synthesize)</button>{' '}
        <button onClick={() => runStage(4)}>Run Stage 4 (Master)</button>
      </div>

      {error ? (
        <div style={{ color: 'red' }}>Error: {error}. Please Run Stage 1 first!</div>
      ) : (
        <table border="1" cellPadding="10" style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
          <thead style={{ background: '#f4f4f4' }}>
            <tr>
              <th width="5%">ID</th>
              <th width="10%">Type</th>
              <th width="35%">Source Text (Original)</th>
              <th width="35%">Phonetic Script (Editable)</th>
              <th width="15%">Audio Preview</th>
            </tr>
          </thead>
          <tbody>
            {segments.map((seg) => (
              <tr key={seg.id}>
                <td>{seg.id}</td>
                <td>
                  <select defaultValue={seg.segment_type}>
                    <option value="prose">Prose</option>
                    <option value="shloka">Shloka</option>
                    <option value="heading">Heading</option>
                    <option value="quote">Quote</option>
                  </select>
                </td>
                <td>{seg.source_text}</td>
                <td>
                  <textarea 
                    defaultValue={seg.pronunciation_text || ""} 
                    rows="3" 
                    style={{ width: '100%', padding: '5px' }} 
                  />
                </td>
                <td>
                  <audio 
                    controls 
                    src={`${API_BASE}/api/projects/${project}/audio/${seg.id}`} 
                    style={{ width: '150px' }}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

export default Editor
