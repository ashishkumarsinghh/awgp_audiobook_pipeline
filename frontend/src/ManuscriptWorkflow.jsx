import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowPathIcon, CheckCircleIcon, DocumentTextIcon } from '@heroicons/react/24/solid'
import { API_BASE } from './config'

async function request(url, options, token) {
  const response = await fetch(`${API_BASE}${url}`, {
    ...options,
    headers: { ...(options?.headers || {}), Authorization: `Bearer ${token}` },
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.detail || 'Manuscript operation failed')
  return data
}

export default function ManuscriptWorkflow({ project, token, projectDetails }) {
  const [content, setContent] = useState('')
  const [revision, setRevision] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const load = async () => {
    const data = await request(`/api/projects/${encodeURIComponent(project)}/manuscript`, {}, token)
    setContent(data.content)
    setRevision(data.revision || '')
  }

  useEffect(() => {
    load().catch((err) => setError(err.message))
  }, [project])

  const run = async (action) => {
    setBusy(action)
    setError('')
    setMessage('')
    try {
      if (action === 'save') {
        const data = await request(`/api/projects/${encodeURIComponent(project)}/manuscript`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content }),
        }, token)
        setRevision(data.revision || '')
        setMessage('Manuscript saved. Run Validate before building audio.')
      } else {
        const data = await request(`/api/projects/${encodeURIComponent(project)}/manuscript/${action}`, { method: 'POST' }, token)
        setMessage(action === 'build' ? `Build ${data.build_id} completed.` : `${action[0].toUpperCase()}${action.slice(1)} completed.`)
        if (action === 'undo') await load()
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-white border-b border-slate-200 px-6 py-3 flex items-center justify-between">
        <div>
          <Link to="/dashboard" className="text-sm text-slate-500 hover:text-blue-600">← Projects</Link>
          <h1 className="text-xl font-bold text-slate-900 mt-2 flex items-center gap-2"><DocumentTextIcon className="w-5 h-5 text-indigo-600" />{project}</h1>
          <p className="text-xs text-slate-500 mt-1">Manuscript workflow · {projectDetails?.status || 'Ready'}</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => run('validate')} disabled={Boolean(busy)} className="px-3 py-2 rounded-md border border-slate-300 bg-white text-xs font-semibold disabled:opacity-50">{busy === 'validate' ? 'Validating…' : 'Validate'}</button>
          <button onClick={() => run('build')} disabled={Boolean(busy)} className="px-3 py-2 rounded-md bg-indigo-600 text-white text-xs font-semibold disabled:opacity-50">{busy === 'build' ? <ArrowPathIcon className="w-4 h-4 animate-spin" /> : 'Build audio'}</button>
          <button onClick={() => run('submit')} disabled={Boolean(busy)} className="px-3 py-2 rounded-md bg-green-600 text-white text-xs font-semibold disabled:opacity-50">{busy === 'submit' ? 'Submitting…' : 'Submit review'}</button>
        </div>
      </header>
      <main className="max-w-6xl mx-auto p-6">
        <div className="rounded-lg border border-indigo-100 bg-indigo-50 px-4 py-3 text-sm text-indigo-900 mb-4">
          This project is connected to the same authoritative <code>manuscript.txt</code> workflow used by <code>run.py</code>. The legacy stage editor is disabled for this book.
        </div>
        {error && <div className="mb-4 rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">{error}</div>}
        {message && <div className="mb-4 rounded-md bg-green-50 border border-green-200 px-4 py-3 text-sm text-green-700 flex items-center gap-2"><CheckCircleIcon className="w-4 h-4" />{message}</div>}
        <div className="bg-white rounded-lg border border-slate-200 shadow-sm p-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-semibold text-slate-900">Authoritative manuscript</h2>
            <span className="text-xs text-slate-400">Revision {revision ? revision.slice(0, 12) : '—'}</span>
          </div>
          <textarea value={content} onChange={(event) => setContent(event.target.value)} className="w-full min-h-[60vh] rounded-md border border-slate-300 p-4 font-mono text-sm leading-6 focus:border-indigo-500 focus:ring-indigo-500" spellCheck="false" />
          <div className="mt-3 flex justify-end gap-2">
            <button onClick={() => run('undo')} disabled={Boolean(busy)} className="px-3 py-2 rounded-md border border-slate-300 text-xs font-semibold disabled:opacity-50">Undo</button>
            <button onClick={() => run('save')} disabled={Boolean(busy)} className="px-4 py-2 rounded-md bg-slate-800 text-white text-xs font-semibold disabled:opacity-50">{busy === 'save' ? 'Saving…' : 'Save manuscript'}</button>
          </div>
        </div>
      </main>
    </div>
  )
}
