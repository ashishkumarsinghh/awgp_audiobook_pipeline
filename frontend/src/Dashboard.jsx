import { useState, useContext } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { 
  PlusIcon, 
  BookOpenIcon, 
  ClockIcon, 
  UserCircleIcon, 
  ArrowRightOnRectangleIcon, 
  HandRaisedIcon,
  CheckCircleIcon, 
  ArrowPathIcon
} from '@heroicons/react/24/solid'
import { AuthContext } from './AuthContext'

function Dashboard() {
  const { user, logout } = useContext(AuthContext)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [newProjectName, setNewProjectName] = useState('')
  const [file, setFile] = useState(null)
  
  const [reqName, setReqName] = useState('')
  const [reqEmail, setReqEmail] = useState('')
  const [reqPhone, setReqPhone] = useState('')
  
  // Track selected user for each project assignment in the table
  const [selectedAssignments, setSelectedAssignments] = useState({})

  // Fetch projects
  const { data: dashboardData = { projects: [], metrics: {} }, isLoading: loadingProjects, isError: errorProjects } = useQuery({
    queryKey: ['projects'],
    queryFn: async () => {
      const res = await fetch(`http://localhost:8000/api/projects`, {
        headers: { 'Authorization': `Bearer ${user?.token}` }
      })
      if (res.status === 401) {
        logout()
        navigate('/login')
        throw new Error('Session expired. Please sign in again.')
      }
      if (!res.ok) throw new Error('Failed to fetch projects')
      return res.json()
    },
    enabled: !!user?.token
  })

  // Fetch admin allocation requests
  const { data: adminData = { users: [], unassigned_projects: [] } } = useQuery({
    queryKey: ['admin-allocations'],
    queryFn: async () => {
      const res = await fetch('http://localhost:8000/api/admin/allocation-requests', {
        headers: { 'Authorization': `Bearer ${user.token}` }
      })
      if (!res.ok) throw new Error('Failed to fetch allocations')
      return res.json()
    },
    enabled: user?.role === 'admin'
  })

  // Fetch editors list for admin dropdown
  const { data: editorsList = [] } = useQuery({
    queryKey: ['editors-list'],
    queryFn: async () => {
      const res = await fetch('http://localhost:8000/api/users', {
        headers: { 'Authorization': `Bearer ${user.token}` }
      })
      if (!res.ok) throw new Error('Failed to fetch editors')
      return res.json()
    },
    enabled: user?.role === 'admin'
  })

  // Upload project mutation
  const uploadMutation = useMutation({
    mutationFn: async (formData) => {
      const res = await fetch('http://localhost:8000/api/projects', {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${user.token}` },
        body: formData
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Upload failed')
      }
      return res.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      queryClient.invalidateQueries({ queryKey: ['admin-allocations'] })
      setIsModalOpen(false)
      setNewProjectName('')
      setFile(null)
    }
  })

  // Volunteer request allocation mutation
  const requestAllocationMutation = useMutation({
    mutationFn: async (payload) => {
      const res = await fetch('http://localhost:8000/api/users/request-allocation', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${user.token}` },
        body: JSON.stringify(payload)
      })
      if (!res.ok) throw new Error('Request failed')
      return res.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
    }
  })

  // Allocate user via admin request section
  const allocateMutation = useMutation({
    mutationFn: async ({ userId, projectId }) => {
      const formData = new FormData()
      formData.append('user_id', userId)
      formData.append('project_id', projectId)
      const res = await fetch('http://localhost:8000/api/admin/allocate-user', {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${user.token}` },
        body: formData
      })
      if (!res.ok) throw new Error('Allocation failed')
      return res.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      queryClient.invalidateQueries({ queryKey: ['admin-allocations'] })
    }
  })

  // Direct assign mutation for table dropdown
  const assignMutation = useMutation({
    mutationFn: async ({ projectName, userId }) => {
      const formData = new FormData()
      if (userId) formData.append('user_id', userId)
      const res = await fetch(`http://localhost:8000/api/projects/${projectName}/assign`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${user.token}` },
        body: formData
      })
      if (!res.ok) throw new Error('Assignment failed')
      return res.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      queryClient.invalidateQueries({ queryKey: ['admin-allocations'] })
    }
  })

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const handleUpload = (e) => {
    e.preventDefault()
    if (!newProjectName || !file) return alert('Name and file required')
    const formData = new FormData()
    formData.append('name', newProjectName.replace(/[^a-zA-Z0-9_-]/g, '_'))
    formData.append('file', file)
    uploadMutation.mutate(formData)
  }

  const handleRequestAllocation = (e) => {
    e.preventDefault()
    requestAllocationMutation.mutate({ full_name: reqName, email: reqEmail, phone: reqPhone })
  }

  const formatStageBadge = (status) => {
    switch (status) {
      case '05_Mastered':
        return <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-green-100 text-green-800"><CheckCircleIcon className="w-4 h-4 mr-1 text-green-600"/> Mastered</span>
      case '04_Audio_Review':
        return <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-purple-100 text-purple-800"><CheckCircleIcon className="w-4 h-4 mr-1 text-purple-600"/> Audio Review</span>
      case '03_Synthesizing':
        return <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-indigo-100 text-indigo-800 animate-pulse"><ArrowPathIcon className="w-4 h-4 mr-1 text-indigo-600 animate-spin"/> Synthesizing Audio</span>
      case '03_Phonetics':
        return <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-100 text-blue-800"><ArrowPathIcon className="w-4 h-4 mr-1 text-blue-600"/> Phonetics</span>
      case '02_Segmentation':
        return <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-800"><ArrowPathIcon className="w-4 h-4 mr-1 text-amber-600"/> Segmentation</span>
      case '01_OCR_Done':
        return <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-teal-100 text-teal-800"><CheckCircleIcon className="w-4 h-4 mr-1 text-teal-600"/> Text Refinement</span>
      default:
        return <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-100 text-slate-700"><ClockIcon className="w-4 h-4 mr-1 text-slate-500"/> PDF Ingested</span>
    }
  }

  const { projects = [], metrics = {} } = dashboardData
  const { users: allocationRequests = [], unassigned_projects: unassignedProjects = [] } = adminData

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col">
      {/* Header */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-20">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <Link to="/" className="flex items-center group">
            <BookOpenIcon className="h-8 w-8 text-blue-600 mr-3 group-hover:scale-105 transition-transform" />
            <div>
              <h1 className="text-xl font-bold text-slate-800 group-hover:text-blue-600 transition-colors">AWGP Audiobook Production</h1>
              <span className="text-xs text-slate-400 font-medium">Scanned PDF to Mastered Audio Pipeline</span>
            </div>
          </Link>
          <div className="flex items-center space-x-6">
            <div className="flex items-center text-sm font-medium text-slate-600">
              <UserCircleIcon className="h-8 w-8 mr-2 text-slate-400" />
              <div className="flex flex-col">
                <span className="font-semibold text-slate-800">{user?.username}</span>
                <span className="text-xs text-blue-600 uppercase font-bold tracking-wider">{user?.role}</span>
              </div>
            </div>
            {user?.role === 'admin' && (
              <button 
                onClick={() => setIsModalOpen(true)} 
                className="flex items-center rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 transition cursor-pointer"
              >
                <PlusIcon className="-ml-0.5 mr-1.5 h-5 w-5" /> Add Book to Pool
              </button>
            )}
            <button onClick={handleLogout} title="Logout" className="text-slate-400 hover:text-slate-600 transition cursor-pointer">
              <ArrowRightOnRectangleIcon className="w-6 h-6"/>
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 flex-1 w-full">
        
        {/* Admin Dashboard Metric Cards */}
        {user?.role === 'admin' && (
          <div className="mb-8">
            <h2 className="text-lg font-bold text-slate-800 mb-4">Production Overview</h2>
            <dl className="grid grid-cols-1 gap-5 sm:grid-cols-4">
              <div className="rounded-xl bg-white p-5 shadow-sm border border-slate-200">
                <dt className="text-xs font-semibold text-slate-500 uppercase">Total Books</dt>
                <dd className="mt-2 text-3xl font-bold text-slate-900">{metrics.total || 0}</dd>
              </div>
              <div className="rounded-xl bg-white p-5 shadow-sm border border-slate-200">
                <dt className="text-xs font-semibold text-amber-600 uppercase">Unassigned Books</dt>
                <dd className="mt-2 text-3xl font-bold text-amber-600">{metrics.unassigned || 0}</dd>
              </div>
              <div className="rounded-xl bg-white p-5 shadow-sm border border-slate-200">
                <dt className="text-xs font-semibold text-blue-600 uppercase">In Production</dt>
                <dd className="mt-2 text-3xl font-bold text-blue-600">{metrics.in_progress || 0}</dd>
              </div>
              <div className="rounded-xl bg-white p-5 shadow-sm border border-slate-200">
                <dt className="text-xs font-semibold text-green-600 uppercase">Mastered Final</dt>
                <dd className="mt-2 text-3xl font-bold text-green-600">{metrics.mastered || 0}</dd>
              </div>
            </dl>
          </div>
        )}

        {/* Volunteer Allocation Requests Section (Admin Only) */}
        {user?.role === 'admin' && allocationRequests.length > 0 && (
          <div className="mb-8 p-6 bg-blue-50 rounded-xl border border-blue-200 shadow-sm">
            <h3 className="text-base font-bold text-blue-900 mb-4 flex items-center">
              <HandRaisedIcon className="w-5 h-5 mr-2 text-blue-600"/> 
              Pending Volunteer Allocation Requests ({allocationRequests.length})
            </h3>
            <ul className="space-y-3">
              {allocationRequests.map(req => (
                <li key={req.id} className="flex flex-col sm:flex-row sm:items-center justify-between bg-white p-4 rounded-lg shadow-sm border border-slate-200 gap-4">
                  <div>
                    <p className="text-sm font-bold text-slate-900">{req.full_name || req.username} <span className="text-xs text-slate-500 font-normal">(@{req.username})</span></p>
                    <p className="text-xs text-slate-500">{req.email || 'No email'} • {req.phone || 'No phone'}</p>
                  </div>
                  <div className="flex items-center gap-3">
                    <select 
                      className="text-sm border border-slate-300 rounded-md px-3 py-1.5 bg-white text-slate-700 focus:ring-blue-500 focus:border-blue-500" 
                      id={`assign-${req.id}`}
                      defaultValue=""
                    >
                      <option value="">-- Choose Book to Allocate --</option>
                      {unassignedProjects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                    </select>
                    <button 
                      onClick={() => {
                        const selectEl = document.getElementById(`assign-${req.id}`)
                        if (!selectEl || !selectEl.value) return alert('Please select a book to allocate')
                        allocateMutation.mutate({ userId: req.id, projectId: selectEl.value })
                      }}
                      disabled={allocateMutation.isPending}
                      className="bg-blue-600 text-white px-4 py-1.5 rounded-md text-sm font-semibold hover:bg-blue-500 disabled:opacity-50 transition cursor-pointer flex items-center gap-1.5"
                    >
                      {allocateMutation.isPending && <ArrowPathIcon className="w-4 h-4 animate-spin"/>}
                      {allocateMutation.isPending ? 'Allocating...' : 'Confirm Allocation'}
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Editor Dashboard - Empty State & Request Form */}
        {user?.role === 'editor' && projects.length === 0 && (
          <div className="max-w-xl mx-auto mt-8 bg-white p-8 rounded-xl shadow-sm border border-slate-200 text-center">
            {requestAllocationMutation.isSuccess ? (
              <div className="py-8">
                <CheckCircleIcon className="mx-auto h-16 w-16 text-green-500 mb-4" />
                <h3 className="text-xl font-bold text-slate-900">Allocation Request Submitted!</h3>
                <p className="text-slate-500 mt-2 text-sm">
                  An administrator has been notified and will allocate an audiobook project to your workspace shortly.
                </p>
              </div>
            ) : (
              <form onSubmit={handleRequestAllocation} className="space-y-5 text-left">
                <div className="text-center">
                  <div className="w-12 h-12 rounded-full bg-blue-50 text-blue-600 flex items-center justify-center mx-auto mb-3">
                    <HandRaisedIcon className="w-6 h-6" />
                  </div>
                  <h2 className="text-xl font-bold text-slate-900">Request Book Allocation</h2>
                  <p className="text-slate-500 text-sm mt-1">You do not currently have any assigned books in your workspace. Fill in your details to get started.</p>
                </div>
                <div>
                  <label className="block text-xs font-semibold uppercase text-slate-600 mb-1">Full Name</label>
                  <input type="text" required value={reqName} onChange={e=>setReqName(e.target.value)} placeholder="e.g. Acharya Sharma" className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none" />
                </div>
                <div>
                  <label className="block text-xs font-semibold uppercase text-slate-600 mb-1">Email Address</label>
                  <input type="email" required value={reqEmail} onChange={e=>setReqEmail(e.target.value)} placeholder="editor@awgp.org" className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none" />
                </div>
                <div>
                  <label className="block text-xs font-semibold uppercase text-slate-600 mb-1">Mobile / WhatsApp Number</label>
                  <input type="tel" required value={reqPhone} onChange={e=>setReqPhone(e.target.value)} placeholder="+91 9876543210" className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none" />
                </div>
                <button 
                  type="submit" 
                  disabled={requestAllocationMutation.isPending} 
                  className="w-full bg-blue-600 text-white font-semibold py-2.5 rounded-md hover:bg-blue-700 transition disabled:opacity-50 cursor-pointer flex justify-center items-center gap-2"
                >
                  {requestAllocationMutation.isPending && <ArrowPathIcon className="w-4 h-4 animate-spin"/>}
                  {requestAllocationMutation.isPending ? 'Submitting...' : 'Request Book Allocation'}
                </button>
              </form>
            )}
          </div>
        )}

        {/* Project List Table */}
        <div className="bg-white shadow-sm ring-1 ring-slate-200 rounded-xl overflow-hidden mt-6">
          <div className="px-6 py-4 border-b border-slate-200 bg-slate-50 flex items-center justify-between">
            <h2 className="text-base font-bold text-slate-800">
              {user?.role === 'admin' ? 'All Audiobook Projects' : 'Audiobook Projects & Workspaces'}
            </h2>
            <span className="text-xs font-semibold text-slate-500">
              {projects.length} {projects.length === 1 ? 'Project' : 'Projects'}
            </span>
          </div>
          {loadingProjects ? (
            <div className="p-12 text-center text-slate-500 flex flex-col items-center justify-center">
              <ArrowPathIcon className="w-6 h-6 animate-spin text-blue-600 mb-2"/>
              <span>Loading projects...</span>
            </div>
          ) : errorProjects ? (
            <div className="p-8 text-center text-red-600">
              <p className="font-semibold text-sm mb-2">Failed to load projects</p>
              <button 
                onClick={() => queryClient.invalidateQueries({ queryKey: ['projects'] })}
                className="px-3 py-1.5 bg-red-100 hover:bg-red-200 text-red-800 rounded-md text-xs font-semibold cursor-pointer"
              >
                Retry
              </button>
            </div>
          ) : projects.length === 0 ? (
            <div className="p-12 text-center text-slate-500">
              <BookOpenIcon className="w-12 h-12 text-slate-300 mx-auto mb-3" />
              <p className="font-medium text-slate-700">No projects found in pool</p>
              {user?.role === 'admin' && (
                <p className="text-sm text-slate-400 mt-1">Click "Add Book to Pool" above to upload your first scanned PDF.</p>
              )}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
                <thead className="bg-slate-50 text-slate-500 text-xs uppercase font-semibold">
                  <tr>
                    <th className="py-3.5 pl-6 pr-3">Book / Identifier</th>
                    <th className="px-3 py-3.5">Pipeline Stage</th>
                    <th className="px-3 py-3.5">Assigned Editor</th>
                    <th className="py-3.5 pl-3 pr-6 text-right">Workspace</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {projects.map((project) => (
                    <tr key={project.name} className="hover:bg-slate-50/80 transition-colors">
                      <td className="py-4 pl-6 pr-3 font-semibold text-slate-900">
                        <Link to={`/project/${project.name}`} className="hover:text-blue-600 flex items-center gap-2">
                          <BookOpenIcon className="w-4 h-4 text-blue-500"/>
                          {project.name}
                        </Link>
                      </td>
                      <td className="px-3 py-4">{formatStageBadge(project.status)}</td>
                      
                      {/* Allocation Column */}
                      <td className="px-3 py-4">
                        {user?.role === 'admin' ? (
                          <div className="flex items-center gap-2">
                            <select 
                              className="text-xs border border-slate-200 rounded-md px-2 py-1.5 bg-slate-50 text-slate-700 focus:bg-white focus:ring-1 focus:ring-blue-500"
                              value={selectedAssignments[project.name] !== undefined ? selectedAssignments[project.name] : (project.assigned_to || '')}
                              onChange={(e) => setSelectedAssignments({ ...selectedAssignments, [project.name]: e.target.value })}
                            >
                              <option value="">-- Unassigned --</option>
                              {editorsList.map(u => (
                                <option key={u.id} value={u.id}>{u.username} {u.full_name ? `(${u.full_name})` : ''}</option>
                              ))}
                            </select>
                            
                            <button
                              onClick={() => {
                                const targetUserId = selectedAssignments[project.name] !== undefined ? selectedAssignments[project.name] : (project.assigned_to || '')
                                assignMutation.mutate({ projectName: project.name, userId: targetUserId })
                              }}
                              disabled={assignMutation.isPending}
                              className="text-xs bg-slate-100 hover:bg-blue-50 hover:text-blue-600 text-slate-600 border border-slate-200 rounded px-2.5 py-1 font-medium transition cursor-pointer disabled:opacity-50"
                            >
                              Save
                            </button>
                          </div>
                        ) : (
                          <div className="text-xs">
                            {project.is_assigned_to_me ? (
                              <span className="inline-flex items-center px-2.5 py-0.5 rounded-full font-bold bg-blue-50 text-blue-700 border border-blue-200">
                                Assigned to You
                              </span>
                            ) : project.assigned_to ? (
                              <span className="text-slate-500 font-medium">
                                @{project.assigned_username}
                              </span>
                            ) : (
                              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold bg-amber-50 text-amber-700 border border-amber-200">
                                Unassigned
                              </span>
                            )}
                          </div>
                        )}
                      </td>

                      <td className="py-4 pl-3 pr-6 text-right">
                        <Link 
                          to={`/project/${project.name}`} 
                          className="inline-flex items-center text-xs font-semibold text-blue-600 hover:text-blue-800 bg-blue-50 hover:bg-blue-100 px-3 py-1.5 rounded-md transition"
                        >
                          Open Workspace →
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </main>

      {/* Upload Modal (Admin Only) */}
      {isModalOpen && user?.role === 'admin' && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs">
          <div className="relative bg-white rounded-2xl shadow-xl w-full max-w-md p-6 overflow-hidden">
            <h3 className="text-lg font-bold text-slate-900">Add Book to Pool</h3>
            <p className="text-xs text-slate-500 mt-1 mb-5">
              Upload a scanned or digital PDF. It will be stored as the authoritative source artifact and initialized into the pipeline.
            </p>
            <form onSubmit={handleUpload} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold uppercase text-slate-600 mb-1">Project Identifier</label>
                <input 
                  type="text" 
                  required 
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none" 
                  placeholder="e.g. brahma_sandhya" 
                  value={newProjectName} 
                  onChange={e => setNewProjectName(e.target.value)} 
                />
              </div>
              <div>
                <label className="block text-xs font-semibold uppercase text-slate-600 mb-1">Source PDF Document (.pdf)</label>
                <input 
                  type="file" 
                  accept=".pdf" 
                  required 
                  className="w-full text-xs text-slate-500 file:mr-3 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-xs file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100 cursor-pointer border border-slate-200 rounded-md p-1" 
                  onChange={e => setFile(e.target.files[0])} 
                />
              </div>
              {uploadMutation.isError && (
                <div className="text-xs text-red-600 bg-red-50 p-2.5 rounded border border-red-200">
                  {uploadMutation.error.message}
                </div>
              )}
              <div className="flex gap-3 pt-2">
                <button 
                  type="button" 
                  onClick={() => setIsModalOpen(false)} 
                  className="flex-1 rounded-md bg-slate-100 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-200 cursor-pointer transition"
                >
                  Cancel
                </button>
                <button 
                  type="submit" 
                  disabled={uploadMutation.isPending} 
                  className="flex-1 rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-500 disabled:opacity-50 cursor-pointer transition flex items-center justify-center gap-2"
                >
                  {uploadMutation.isPending && <ArrowPathIcon className="w-4 h-4 animate-spin"/>}
                  {uploadMutation.isPending ? 'Uploading...' : 'Upload & Add'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

export default Dashboard
