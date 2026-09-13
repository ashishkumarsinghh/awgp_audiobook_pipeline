import { API_BASE } from './config'
import { useState, useEffect, useContext, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { AuthContext } from './AuthContext'
import { 
  DocumentArrowUpIcon, 
  SpeakerWaveIcon, 
  ArrowPathIcon,
  CheckCircleIcon,
  ArrowDownTrayIcon,
  ChevronRightIcon,
  ClockIcon,
  BookOpenIcon,
  FolderIcon
} from '@heroicons/react/24/solid'
import WaveSurferPlayer from './WaveSurferPlayer'

const steps = [
  { id: 0, name: 'PDF Ingestion', desc: '00_scanned.pdf' },
  { id: 1, name: 'Text Refinement', desc: '02_text_cleaned.txt' },
  { id: 2, name: 'Segmentation', desc: '03_segments.json' },
  { id: 3, name: 'Phonetic Scripting', desc: '04_phonetics.json' },
  { id: 4, name: 'Audio Review', desc: '05_audio_chunks/' },
  { id: 5, name: 'Final Review & Release', desc: '06_mastered.mp3' },
]

const segmentTypes = [
  ['prose', 'Prose'], ['paragraph', 'Paragraph'], ['heading', 'Heading'], ['subheading', 'Subheading'],
  ['shloka', 'Shloka'], ['verse_line', 'Verse line'], ['stanza', 'Stanza'], ['mantra', 'Mantra'],
  ['chant_refrain', 'Chant refrain'], ['quote', 'Quote'], ['dialogue', 'Dialogue'], ['gloss', 'Gloss'],
  ['footnote', 'Footnote'], ['list_item', 'List item'], ['caption', 'Caption'], ['transliteration', 'Transliteration'],
]

function ProjectPipeline() {
  const { id: project } = useParams()
  const { user } = useContext(AuthContext)
  const queryClient = useQueryClient()
  
  const [currentStep, setCurrentStep] = useState(0)
  const [localCleanText, setLocalCleanText] = useState('')
  const [localSegments, setLocalSegments] = useState([])
  const [localPhonetics, setLocalPhonetics] = useState([])
  const [statusInitialized, setStatusInitialized] = useState(false)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [showArtifactsModal, setShowArtifactsModal] = useState(false)
  const [reviewComment, setReviewComment] = useState('')
  const [reviewSeverity, setReviewSeverity] = useState('major')
  const [ttsProvider, setTtsProvider] = useState('edge')
  const [ttsVoice, setTtsVoice] = useState('hi-IN-SwaraNeural')
  const finalAudioRef = useRef(null)
  const [reviewTimestamp, setReviewTimestamp] = useState(0)
  const restoreArtifactMutation = useMutation({
    mutationFn: async (filename) => {
      const res = await fetch(`${API_BASE}/api/projects/${project}/artifacts/${encodeURIComponent(filename)}/restore`, {
        method: 'POST', headers: { 'Authorization': `Bearer ${user.token}` }
      })
      if (!res.ok) { const err = await res.json(); throw new Error(err.detail || 'Could not restore artifact') }
      return res.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['rawText', project] }); queryClient.invalidateQueries({ queryKey: ['segments', project] });
      queryClient.invalidateQueries({ queryKey: ['phonetics', project] }); queryClient.invalidateQueries({ queryKey: ['projectDetails', project] });
      refetchArtifacts();
    }
  })

  // 1. Fetch Project Metadata & Status (polls every 1.5s while audio is synthesizing)
  const { data: projectDetails, isLoading: loadingDetails, isError: errorDetails } = useQuery({
    queryKey: ['projectDetails', project],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/api/projects/${project}`, {
        headers: { 'Authorization': `Bearer ${user.token}` }
      })
      if (!res.ok) throw new Error('Failed to load project details')
      return res.json()
    },
    refetchInterval: (query) => {
      const d = query?.state?.data
      if (d?.status === '04_Synthesizing') return 1500
      return false
    }
  })

  const { data: voiceCatalog = { voices: [] } } = useQuery({
    queryKey: ['ttsVoices'], queryFn: async () => {
      const res = await fetch(`${API_BASE}/api/tts/voices`, { headers: { 'Authorization': `Bearer ${user.token}` } })
      if (!res.ok) throw new Error('Failed to load voices')
      return res.json()
    }
  })
  const { data: ttsSettings } = useQuery({
    queryKey: ['ttsSettings', project], queryFn: async () => {
      const res = await fetch(`${API_BASE}/api/projects/${project}/settings/tts-provider`, { headers: { 'Authorization': `Bearer ${user.token}` } })
      if (!res.ok) throw new Error('Failed to load voice settings')
      return res.json()
    }
  })
  useEffect(() => { if (ttsSettings) { setTtsProvider(ttsSettings.provider); setTtsVoice(ttsSettings.voice) } }, [ttsSettings])
  const saveTtsSettingsMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE}/api/projects/${project}/settings/tts-provider`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${user.token}` }, body: JSON.stringify({ provider: ttsProvider, voice: ttsVoice }) })
      if (!res.ok) { const err = await res.json(); throw new Error(err.detail || 'Could not save voice settings') }
      return res.json()
    },
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['projectDetails', project] }); queryClient.invalidateQueries({ queryKey: ['ttsSettings', project] }) }
  })

  // 2. Fetch Raw and Cleaned Text
  const { data: rawData, isLoading: loadingRaw } = useQuery({
    queryKey: ['rawText', project],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/api/projects/${project}/raw`, {
        headers: { 'Authorization': `Bearer ${user.token}` }
      })
      if (res.status === 404) return { raw_text: '', clean_text: '', text: '', has_clean: false }
      if (!res.ok) throw new Error('Failed to load text')
      return res.json()
    }
  })

  // 3. Fetch Segments
  const { data: segmentsData = [], isLoading: loadingSegments } = useQuery({
    queryKey: ['segments', project],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/api/projects/${project}/segments`, {
        headers: { 'Authorization': `Bearer ${user.token}` }
      })
      if (res.status === 404) return []
      if (!res.ok) throw new Error('Failed to load segments')
      const data = await res.json()
      return Array.isArray(data) ? data : []
    }
  })

  // 4. Fetch Phonetics
    // 5. Fetch Artifacts History
  const { data: artifactsList = [], refetch: refetchArtifacts } = useQuery({
    queryKey: ['artifacts', project],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/api/projects/${project}/artifacts`, {
        headers: { 'Authorization': `Bearer ${user.token}` }
      })
      if (!res.ok) return []
      return res.json()
    }
  })

  const { data: reviewData, refetch: refetchReview } = useQuery({
    queryKey: ['review', project],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/api/projects/${project}/review`, {
        headers: { 'Authorization': `Bearer ${user.token}` }
      })
      if (res.status === 404) return null
      if (!res.ok) throw new Error('Failed to load review candidate')
      return res.json()
    },
    enabled: Boolean(projectDetails?.has_mastered || ['05_Mastered', '06_Pending_Second_Approval', '06_Approved'].includes(projectDetails?.status))
  })

  const reviewIssueMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE}/api/projects/${project}/review/issues`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${user.token}` },
        body: JSON.stringify({ body: reviewComment, severity: reviewSeverity, start_seconds: Math.floor(reviewTimestamp) })
      })
      if (!res.ok) { const err = await res.json(); throw new Error(err.detail || 'Could not save review issue') }
      return res.json()
    },
    onSuccess: () => { setReviewComment(''); refetchReview(); queryClient.invalidateQueries({ queryKey: ['projectDetails', project] }) }
  })

  const reviewDecisionMutation = useMutation({
    mutationFn: async (decision) => {
      const res = await fetch(`${API_BASE}/api/projects/${project}/review/decision`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${user.token}` },
        body: JSON.stringify({ decision })
      })
      if (!res.ok) { const err = await res.json(); throw new Error(err.detail || 'Could not save review decision') }
      return res.json()
    },
    onSuccess: () => { refetchReview(); queryClient.invalidateQueries({ queryKey: ['projectDetails', project] }) }
  })

  const reviewIssueStatusMutation = useMutation({
    mutationFn: async ({ id, status }) => {
      const body = new URLSearchParams({ status })
      const res = await fetch(`${API_BASE}/api/projects/${project}/review/issues/${id}`, {
        method: 'PATCH', headers: { 'Authorization': `Bearer ${user.token}` }, body
      })
      if (!res.ok) { const err = await res.json(); throw new Error(err.detail || 'Could not update issue') }
      return res.json()
    },
    onSuccess: () => { refetchReview(); queryClient.invalidateQueries({ queryKey: ['projectDetails', project] }) }
  })

  const { data: phoneticsData = [], isLoading: loadingPhonetics } = useQuery({
    queryKey: ['phonetics', project],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/api/projects/${project}/phonetics`, {
        headers: { 'Authorization': `Bearer ${user.token}` }
      })
      if (res.status === 404) return []
      if (!res.ok) throw new Error('Failed to load phonetics')
      const data = await res.json()
      return Array.isArray(data) ? data : []
    }
  })

  // Synchronize local states with fetched data
  useEffect(() => {
    if (rawData) {
      setLocalCleanText(rawData.clean_text || rawData.raw_text || rawData.text || '')
    }
  }, [rawData])

  useEffect(() => {
    if (segmentsData && segmentsData.length > 0) {
      setLocalSegments(segmentsData)
    }
  }, [segmentsData])

  useEffect(() => {
    if (phoneticsData && phoneticsData.length > 0) {
      setLocalPhonetics(phoneticsData)
    }
  }, [phoneticsData])

  // Automatically transition and refresh queries when background synthesis completes
  useEffect(() => {
    if (projectDetails?.status === '04_Audio_Review') {
      queryClient.invalidateQueries({ queryKey: ['segments', project] })
      queryClient.invalidateQueries({ queryKey: ['phonetics', project] })
      queryClient.invalidateQueries({ queryKey: ['projectDetails', project] })
      queryClient.invalidateQueries({ queryKey: ['artifacts', project] })
      if (currentStep === 3) {
        setCurrentStep(4)
      }
    }
  }, [projectDetails?.status])

  // Automatically navigate to active stage on first load
  useEffect(() => {
    if (projectDetails && !statusInitialized) {
      const s = projectDetails.status
      if (s === '00_Ingested') {
        setCurrentStep(projectDetails.has_raw_text ? 1 : 0)
      } else if (s === '01_OCR_Done') {
        setCurrentStep(1)
      } else if (s === '02_Segmentation') {
        setCurrentStep(2)
      } else if (s === '03_Phonetics' || s === '04_Synthesizing') {
        setCurrentStep(3)
      } else if (s === '04_Audio_Review') {
        setCurrentStep(4)
      } else if (s === '05_Mastered' || s === '06_Pending_Second_Approval' || s === '06_Approved' || s === '06_Changes_Requested') {
        setCurrentStep(5)
      }
      setStatusInitialized(true)
    }
  }, [projectDetails, statusInitialized])

  // Mutation: Save Clean Text (Stage 1)
  const saveCleanMutation = useMutation({
    mutationFn: async (text) => {
      const res = await fetch(`${API_BASE}/api/projects/${project}/clean`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${user.token}` },
        body: JSON.stringify({ text })
      })
      if (!res.ok) throw new Error('Failed to save cleaned text')
      return res.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['rawText', project] })
      queryClient.invalidateQueries({ queryKey: ['projectDetails', project] })
      queryClient.invalidateQueries({ queryKey: ['artifacts', project] })
    }
  })

  // Mutation: Save Segments (Stage 2)
  const saveSegmentsMutation = useMutation({
    mutationFn: async (updates) => {
      const res = await fetch(`${API_BASE}/api/projects/${project}/segments`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${user.token}` },
        body: JSON.stringify(updates)
      })
      if (!res.ok) throw new Error('Failed to save segments')
      return res.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['segments', project] })
      queryClient.invalidateQueries({ queryKey: ['projectDetails', project] })
      queryClient.invalidateQueries({ queryKey: ['artifacts', project] })
    }
  })

  // Mutation: Save Phonetics (Stage 3)
  const savePhoneticsMutation = useMutation({
    mutationFn: async (updates) => {
      const res = await fetch(`${API_BASE}/api/projects/${project}/phonetics`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${user.token}` },
        body: JSON.stringify(updates)
      })
      if (!res.ok) throw new Error('Failed to save phonetics')
      return res.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['phonetics', project] })
      queryClient.invalidateQueries({ queryKey: ['projectDetails', project] })
      queryClient.invalidateQueries({ queryKey: ['artifacts', project] })
    }
  })

  // Mutation: Run Pipeline Stages
  const runStageMutation = useMutation({
    mutationFn: async (stageNum) => {
      // Auto-save edits prior to running dependent stages
      if (stageNum === 1) {
        await saveCleanMutation.mutateAsync(localCleanText)
      } else if (stageNum === 2) {
        if (localSegments.length > 0) await saveSegmentsMutation.mutateAsync(localSegments)
      } else if (stageNum === 3) {
        if (localPhonetics.length > 0) await savePhoneticsMutation.mutateAsync(localPhonetics)
      }

      const res = await fetch(`${API_BASE}/api/projects/${project}/stage/${stageNum + 1}`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${user.token}` }
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || `Stage ${stageNum} execution failed`)
      }
      return res.json()
    },
    onSuccess: (data, variables) => {
      // Progress to next step on success
      if (variables === 0) setCurrentStep(1)
      if (variables === 1) setCurrentStep(2)
      if (variables === 2) setCurrentStep(3)
      if (variables === 3) {
        queryClient.setQueryData(['projectDetails', project], previous => ({ ...previous, status: data.new_status }))
      }
      if (variables === 4) setCurrentStep(5)

      queryClient.invalidateQueries({ queryKey: ['projectDetails', project] })
      queryClient.invalidateQueries({ queryKey: ['rawText', project] })
      queryClient.invalidateQueries({ queryKey: ['segments', project] })
      queryClient.invalidateQueries({ queryKey: ['phonetics', project] })
      queryClient.invalidateQueries({ queryKey: ['artifacts', project] })
    }
  })

  // Track elapsed seconds during time-consuming operations (e.g. Gemini OCR)
  useEffect(() => {
    let interval = null
    if (runStageMutation.isPending) {
      setElapsedSeconds(0)
      interval = setInterval(() => {
        setElapsedSeconds(prev => prev + 1)
      }, 1000)
    } else {
      setElapsedSeconds(0)
    }
    return () => {
      if (interval) clearInterval(interval)
    }
  }, [runStageMutation.isPending])

  const pdfUrl = `${API_BASE}/api/projects/${project}/pdf?token=${user?.token}`

  const isLoading = loadingDetails || loadingRaw
  const activeSegments = localSegments.length > 0 ? localSegments : segmentsData
  const activePhonetics = localPhonetics.length > 0 ? localPhonetics : (phoneticsData.length > 0 ? phoneticsData : activeSegments)

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col">
      {/* Header */}
      <header className="bg-white border-b border-slate-200 px-6 py-3 flex items-center justify-between shrink-0 shadow-xs z-20">
        <div className="flex items-center gap-3">
          <Link to="/dashboard" className="text-slate-500 hover:text-blue-600 font-semibold text-sm flex items-center gap-1 transition-colors">
            ← Projects
          </Link>
          <ChevronRightIcon className="w-4 h-4 text-slate-300" />
          <div>
            <h1 className="text-base font-bold text-slate-900 flex items-center gap-2">
              {project}
            </h1>
            <div className="flex items-center gap-2 text-xs text-slate-500">
              <span>Status: <strong className="text-slate-700">{projectDetails?.status || 'Loading...'}</strong></span>
              <span>•</span>
              <span>Assigned: <strong className="text-blue-600">{projectDetails?.assigned_username || 'Unassigned'}</strong></span>
            </div>
          </div>
        </div>

        {/* Action button in header if applicable */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 text-xs flex-wrap" title="Choose one of the curated Hindi/Sanskrit voices. Changing voice invalidates matching audio chunks.">
            <select value={ttsProvider} onChange={(e) => { setTtsProvider(e.target.value); const first = voiceCatalog.voices.find(v => v.provider === e.target.value); if (first) setTtsVoice(first.voice) }} className="border border-slate-200 rounded-md px-1.5 py-1 bg-white">
              <option value="edge">Edge</option><option value="google">Google Cloud</option><option value="azure">Azure</option>
            </select>
            <select value={ttsVoice} onChange={(e) => setTtsVoice(e.target.value)} className="border border-slate-200 rounded-md px-1.5 py-1 bg-white max-w-40">
              {voiceCatalog.voices.filter(v => v.provider === ttsProvider).map(v => <option key={v.voice} value={v.voice}>{v.label}</option>)}
            </select>
            <button onClick={() => saveTtsSettingsMutation.mutate()} disabled={saveTtsSettingsMutation.isPending} className="px-2 py-1 rounded-md bg-slate-800 text-white font-semibold disabled:opacity-50">Save voice</button>
          </div>
          <button
            onClick={() => { refetchArtifacts(); setShowArtifactsModal(true); }}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 text-xs font-semibold shadow-2xs transition-colors cursor-pointer"
            title="View saved artifacts with user attribution and timestamps"
          >
            <FolderIcon className="w-3.5 h-3.5 text-blue-600" />
            <span>Artifacts ({artifactsList.length})</span>
          </button>
          {projectDetails?.has_mastered && (
            <a 
              href={`${API_BASE}/api/projects/${project}/mastered?token=${user?.token}`} 
              download 
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-green-600 text-white text-xs font-semibold hover:bg-green-700 transition"
            >
              <ArrowDownTrayIcon className="w-3.5 h-3.5" /> Download Audiobook
            </a>
          )}
        </div>
      </header>

      {/* Main Workspace Area */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Sidebar - Stage Navigation */}
        <aside className="w-64 bg-white border-r border-slate-200 flex flex-col shrink-0 overflow-y-auto hidden md:flex">
          <div className="p-5">
            <h2 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-4">Pipeline Workflow</h2>
            <nav className="space-y-1.5">
              {steps.map((step) => {
                const isActive = currentStep === step.id
                return (
                  <button
                    key={step.id}
                    onClick={() => setCurrentStep(step.id)}
                    className={`w-full text-left px-3.5 py-2.5 rounded-lg border transition-all flex flex-col gap-0.5 cursor-pointer ${
                      isActive 
                        ? 'border-blue-500 bg-blue-50/70 text-blue-900 font-bold shadow-xs' 
                        : 'border-transparent text-slate-600 hover:bg-slate-50 hover:border-slate-200'
                    }`}
                  >
                    <div className="flex items-center justify-between text-xs">
                      <span>{step.id}. {step.name}</span>
                      {isActive && <div className="w-2 h-2 rounded-full bg-blue-600"></div>}
                    </div>
                    <span className="text-[10px] text-slate-400 font-mono">{step.desc}</span>
                  </button>
                )
              })}
            </nav>
          </div>
        </aside>

        {/* Center/Right Content Area */}
        <main className="flex-1 p-4 md:p-6 overflow-hidden flex flex-col relative bg-slate-100/60">
          {projectDetails?.audio_progress?.failed?.length > 0 && (
            <div role="alert" className="mb-4 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
              <p className="font-semibold">Some narration could not be generated. Retry Audio to resume completed chunks.</p>
              {projectDetails.audio_progress.failed.map(chunk => (
                <p key={chunk.id}>{chunk.id}: {chunk.error}</p>
              ))}
            </div>
          )}
          {projectDetails?.audio_progress?.pace_warnings?.length > 0 && (
            <div role="status" className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
              <p className="font-semibold">Pacing needs review</p>
              <p>Some chunks are outside the recommended 115–175 words per minute range. Listen to these chunks and adjust rate or segmentation before mastering.</p>
            </div>
          )}

          {isLoading && (
            <div className="absolute inset-0 bg-white/70 backdrop-blur-xs flex flex-col items-center justify-center z-30">
              <ArrowPathIcon className="w-8 h-8 text-blue-600 animate-spin mb-3" />
              <p className="text-sm font-semibold text-slate-700">Loading pipeline artifacts...</p>
            </div>
          )}

          {errorDetails && (
            <div className="p-4 mb-4 bg-red-50 border border-red-200 text-red-700 rounded-lg text-sm">
              Failed to load project details. Please check connection.
            </div>
          )}

          {runStageMutation.isError && (
            <div className="p-3 mb-3 bg-red-50 border border-red-200 text-red-600 rounded-lg text-xs font-medium">
              Pipeline stage failed: {runStageMutation.error.message}
            </div>
          )}

          {/* ========================================================================= */}
          {/* BACKGROUND SPEECH SYNTHESIS PROGRESS BANNER */}
          {/* ========================================================================= */}
          {projectDetails?.status === '04_Synthesizing' && (
            <div className="mb-4 p-4 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-700 text-white shadow-md flex flex-col gap-3 shrink-0 animate-in fade-in">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-lg bg-white/20 flex items-center justify-center shrink-0">
                    <SpeakerWaveIcon className="w-5 h-5 text-white animate-pulse" />
                  </div>
                  <div>
                    <h3 className="text-xs sm:text-sm font-bold">Neural Speech Synthesis in Progress</h3>
                    <p className="text-[11px] text-blue-100">
                      Generating narration with the selected voice...
                    </p>
                  </div>
                </div>
                <div className="text-left sm:text-right shrink-0">
                  <span className="text-base font-extrabold">{projectDetails?.audio_progress?.percent || 0}%</span>
                  <span className="block text-[11px] text-blue-100">
                    {projectDetails?.audio_progress?.completed || 0} of {projectDetails?.audio_progress?.total || 0} chunks rendered
                  </span>
                </div>
              </div>
              {/* Animated Progress Bar */}
              <div className="w-full bg-black/20 rounded-full h-2 overflow-hidden">
                <div 
                  className="bg-white h-2 rounded-full transition-all duration-500 ease-out shadow-xs" 
                  style={{ width: `${Math.max(5, projectDetails?.audio_progress?.percent || 0)}%` }}
                ></div>
              </div>
              <div className="flex items-center justify-between text-[10px] text-blue-200">
                <span>Audio chunks will automatically load upon completion</span>
                <span className="flex items-center gap-1 font-semibold">
                  <ArrowPathIcon className="w-3 h-3 animate-spin" /> Live polling every 1.5s
                </span>
              </div>
            </div>
          )}

          {/* ========================================================================= */}
          {/* FULL-SCREEN WORKSPACE MODAL OVERLAYS FOR TIME-CONSUMING OPERATIONS */}
          {/* ========================================================================= */}
          {runStageMutation.isPending && (
            <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs">
              <div className="bg-white rounded-2xl shadow-2xl border border-slate-200 max-w-lg w-full p-6 sm:p-8 flex flex-col items-center text-center animate-in fade-in zoom-in-95 duration-150">
                {/* Stage 0: OCR Extraction Modal */}
                {runStageMutation.variables === 0 && (
                  <>
                    <div className="relative mb-5">
                      <div className="w-16 h-16 rounded-2xl bg-blue-50 border border-blue-100 flex items-center justify-center text-blue-600 shadow-inner">
                        <BookOpenIcon className="w-9 h-9" />
                      </div>
                      <div className="absolute -bottom-1 -right-1 w-6 h-6 rounded-full bg-blue-600 text-white flex items-center justify-center shadow-md">
                        <ArrowPathIcon className="w-3.5 h-3.5 animate-spin" />
                      </div>
                    </div>

                    <h3 className="text-base sm:text-lg font-bold text-slate-900 mb-1">
                      Extracting Document with Gemini Vision OCR
                    </h3>
                    <p className="text-xs text-slate-500 max-w-sm mb-4 leading-relaxed">
                      Transcribing vintage Devanagari script page by page and generating authoritative semantic tags with zero hallucination.
                    </p>

                    {/* Live Timer Pill */}
                    <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-50 border border-blue-200 text-blue-700 text-xs font-semibold mb-5">
                      <ClockIcon className="w-4 h-4 text-blue-600 animate-pulse" />
                      <span>Elapsed: {elapsedSeconds}s</span>
                      <span className="text-blue-300">•</span>
                      <span className="text-blue-600 font-normal">Typical duration: 15–30s</span>
                    </div>

                    {/* Progress Step Checklist */}
                    <div className="w-full bg-slate-50 rounded-xl p-4 border border-slate-200 space-y-2.5 text-left mb-5 text-xs">
                      <div className="flex items-center gap-2.5 text-slate-700 font-medium">
                        <CheckCircleIcon className="w-4 h-4 text-green-500 shrink-0" />
                        <span>1. High-resolution rasterization (200 DPI)</span>
                      </div>
                      <div className="flex items-center gap-2.5 text-blue-700 font-semibold">
                        <div className="w-4 h-4 rounded-full border-2 border-blue-600 border-t-transparent animate-spin shrink-0"></div>
                        <span>
                          2. Gemini 3.6 Flash Devanagari Vision Transcription
                          <span className="block text-[11px] text-blue-500 font-normal mt-0.5">
                            {elapsedSeconds < 8 ? 'Loading page images and initiating model...' : elapsedSeconds < 18 ? 'Analyzing glyphs, matras, and conjuncts...' : 'Validating Devanagari spelling against image...'}
                          </span>
                        </span>
                      </div>
                      <div className="flex items-center gap-2.5 text-slate-400">
                        <div className="w-4 h-4 rounded-full border-2 border-slate-300 shrink-0"></div>
                        <span>3. Formatting semantic tags (&lt;prose&gt;, &lt;shloka&gt;, &lt;heading&gt;)</span>
                      </div>
                    </div>

                    {/* Progress Bar */}
                    <div className="w-full bg-slate-100 rounded-full h-2 overflow-hidden mb-2">
                      <div 
                        className="bg-blue-600 h-2 rounded-full transition-all duration-700 ease-out"
                        style={{ width: `${Math.min(95, Math.max(15, elapsedSeconds * 4))}%` }}
                      ></div>
                    </div>
                    <span className="text-[11px] text-slate-400">Please keep this window open while OCR extraction completes.</span>
                  </>
                )}

                {/* Stage 1: Segmentation Modal */}
                {runStageMutation.variables === 1 && (
                  <>
                    <div className="w-14 h-14 rounded-2xl bg-amber-50 text-amber-600 flex items-center justify-center mb-4">
                      <ArrowPathIcon className="w-7 h-7 animate-spin" />
                    </div>
                    <h3 className="text-base font-bold text-slate-900 mb-1">Segmenting Cleaned Text</h3>
                    <p className="text-xs text-slate-500 mb-4 max-w-sm">
                      Analyzing sentence boundaries, punctuation, and verse tags to create speech narration units...
                    </p>
                    <div className="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
                      <div className="bg-amber-500 h-1.5 rounded-full w-3/4 animate-pulse"></div>
                    </div>
                  </>
                )}

                {/* Stage 2: Phonetics Modal */}
                {runStageMutation.variables === 2 && (
                  <>
                    <div className="w-14 h-14 rounded-2xl bg-blue-50 text-blue-600 flex items-center justify-center mb-4">
                      <ArrowPathIcon className="w-7 h-7 animate-spin" />
                    </div>
                    <h3 className="text-base font-bold text-slate-900 mb-1">Applying Phonetics & Prosody</h3>
                    <p className="text-xs text-slate-500 mb-4 max-w-sm">
                      Applying AWGP pronunciation overrides, Vedic sandhi rules, and prosody parameters...
                    </p>
                    <div className="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
                      <div className="bg-blue-600 h-1.5 rounded-full w-3/4 animate-pulse"></div>
                    </div>
                  </>
                )}

                {/* Stage 3: Audio Synthesis Trigger Modal */}
                {runStageMutation.variables === 3 && (
                  <>
                    <div className="w-14 h-14 rounded-2xl bg-indigo-50 text-indigo-600 flex items-center justify-center mb-4">
                      <SpeakerWaveIcon className="w-7 h-7 animate-pulse" />
                    </div>
                    <h3 className="text-base font-bold text-slate-900 mb-1">Queuing Speech Synthesis</h3>
                    <p className="text-xs text-slate-500 mb-4 max-w-sm">
                      Starting background audio synthesis for narration chunks...
                    </p>
                    <div className="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
                      <div className="bg-indigo-600 h-1.5 rounded-full w-2/3 animate-pulse"></div>
                    </div>
                  </>
                )}

                {/* Stage 4: Mastering Modal */}
                {runStageMutation.variables === 4 && (
                  <>
                    <div className="w-14 h-14 rounded-2xl bg-green-50 text-green-600 flex items-center justify-center mb-4">
                      <SpeakerWaveIcon className="w-7 h-7 text-green-600 animate-pulse" />
                    </div>
                    <h3 className="text-base font-bold text-slate-900 mb-1">Mastering Final Audiobook</h3>
                    <p className="text-xs text-slate-500 mb-4 max-w-sm">
                      Concatenating audio chunks, applying ffmpeg EBU R128 loudness normalization (-16 LUFS), and exporting master MP3...
                    </p>
                    <div className="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
                      <div className="bg-green-600 h-1.5 rounded-full w-4/5 animate-pulse"></div>
                    </div>
                  </>
                )}
              </div>
            </div>
          )}

          {/* ========================================================================= */}
          {/* STAGE 0: PDF INGESTION & RUN OCR */}
          {/* ========================================================================= */}
          {currentStep === 0 && (
            <div className="flex flex-col lg:flex-row h-full gap-4">
              {/* Left: Source PDF */}
              <div className="flex-1 bg-white rounded-xl shadow-xs border border-slate-200 overflow-hidden flex flex-col">
                <div className="bg-slate-50 px-4 py-3 border-b border-slate-200 flex justify-between items-center shrink-0">
                  <h2 className="text-xs font-bold uppercase text-slate-700">Allocated Source PDF</h2>
                  <span className="text-xs text-slate-400 font-mono">00_scanned.pdf</span>
                </div>

                <div className="mx-4 mt-3 mb-2 rounded-lg border border-blue-100 bg-blue-50/60 p-3 text-[11px] text-blue-900">
                  <p className="font-semibold mb-1">How rate and pitch affect listening</p>
                  <div className="grid sm:grid-cols-3 gap-2 text-blue-800">
                    <span><b>Rate</b>: -10% is slower and clearer but lengthens the book; +10% is faster but may reduce clarity.</span>
                    <span><b>Pitch</b>: small changes (about ±2 semitones/Hz) deepen or brighten the voice; larger changes can sound artificial.</span>
                    <span><b>Pronunciation</b>: changes only the spoken form. The printed source remains unchanged and can be restored.</span>
                  </div>
                  <p className="mt-2 text-[10px] text-blue-700">Preview one segment after changing a value. Provider units vary, so keep adjustments conservative.</p>
                </div>
                <div className="flex-1 relative bg-slate-100">
                  <iframe src={pdfUrl} className="absolute inset-0 w-full h-full border-0" title="Source PDF Viewer" />
                </div>
              </div>

              {/* Right: OCR Action Card */}
              <div className="w-full lg:w-96 bg-white rounded-xl shadow-xs border border-slate-200 p-6 flex flex-col justify-between shrink-0">
                <div>
                  <div className="w-12 h-12 rounded-full bg-blue-50 text-blue-600 flex items-center justify-center mb-4">
                    <DocumentArrowUpIcon className="w-6 h-6" />
                  </div>
                  <h3 className="text-base font-bold text-slate-900 mb-2">Stage 0: Optical Character Recognition</h3>
                  <p className="text-xs text-slate-500 leading-relaxed mb-6">
                    This PDF has been allocated to your workspace. Run OCR extraction now to convert the Devanagari/Hindi scanned pages into authoritative raw text.
                  </p>
                  
                  {projectDetails?.has_raw_text ? (
                    <div className="p-3 bg-green-50 border border-green-200 rounded-lg text-xs text-green-800 mb-4 flex items-center gap-2">
                      <CheckCircleIcon className="w-4 h-4 text-green-600 shrink-0" />
                      <span>OCR has already been extracted for this project.</span>
                    </div>
                  ) : null}
                </div>

                <div className="space-y-3">
                  <button 
                    onClick={() => runStageMutation.mutate(0)} 
                    disabled={projectDetails?.status === '04_Synthesizing' || runStageMutation.isPending} 
                    className="w-full bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2.5 rounded-lg text-xs transition flex items-center justify-center gap-2 shadow-xs cursor-pointer disabled:opacity-50"
                  >
                    {runStageMutation.isPending && <ArrowPathIcon className="w-4 h-4 animate-spin"/>}
                    {runStageMutation.isPending ? 'Extracting OCR Text...' : 'Run OCR Extraction (Stage 0)'}
                  </button>

                  <button 
                    onClick={() => setCurrentStep(1)} 
                    className="w-full bg-slate-100 hover:bg-slate-200 text-slate-700 font-semibold py-2 rounded-lg text-xs transition cursor-pointer"
                  >
                    Skip to Text Refinement →
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* ========================================================================= */}
          {/* STAGE 1: TEXT REFINEMENT (SIDE BY SIDE: PDF vs OCR TEXT) */}
          {/* ========================================================================= */}
          {currentStep === 1 && (
            <div className="flex flex-col lg:flex-row h-full gap-4">
              {/* Left Column: PDF Viewer */}
              <div className="flex-1 bg-white rounded-xl shadow-xs border border-slate-200 overflow-hidden flex flex-col">
                <div className="bg-slate-50 px-4 py-2.5 border-b border-slate-200 flex justify-between items-center shrink-0">
                  <h2 className="text-xs font-bold uppercase text-slate-700">Source Document (PDF)</h2>
                  <span className="text-[10px] text-slate-400 font-mono">00_scanned.pdf</span>
                </div>
                <div className="flex-1 relative bg-slate-100">
                  <iframe src={pdfUrl} className="absolute inset-0 w-full h-full border-0" title="Source PDF" />
                </div>
              </div>

              {/* Right Column: OCR Text Editor */}
              <div className="flex-1 bg-white rounded-xl shadow-xs border border-slate-200 overflow-hidden flex flex-col">
                <div className="bg-slate-50 px-4 py-2.5 border-b border-slate-200 flex items-center justify-between shrink-0 gap-2">
                  <div>
                    <h2 className="text-xs font-bold uppercase text-slate-800">Refine Extracted Text</h2>
                    <span className="text-[10px] text-slate-400 font-mono">02_text_cleaned.txt</span>
                  </div>
                  <div className="flex items-center gap-2">
                    {rawData?.raw_text && (
                      <button 
                        onClick={() => setLocalCleanText(rawData.raw_text)} 
                        title="Reset editor text to the original raw OCR extraction"
                        className="px-2.5 py-1.5 bg-white hover:bg-slate-50 text-slate-600 border border-slate-300 rounded-md text-xs font-medium shadow-xs transition cursor-pointer flex items-center gap-1"
                      >
                        <ArrowPathIcon className="w-3.5 h-3.5" />
                        Reset to OCR
                      </button>
                    )}
                    <button 
                      onClick={() => runStageMutation.mutate(0)} 
                      disabled={projectDetails?.status === '04_Synthesizing' || runStageMutation.isPending}
                      title="Re-run Gemini OCR on the source PDF"
                      className="px-2.5 py-1.5 bg-white hover:bg-slate-50 text-slate-700 border border-slate-300 rounded-md text-xs font-medium shadow-xs transition cursor-pointer flex items-center gap-1 disabled:opacity-50"
                    >
                      {runStageMutation.isPending && <ArrowPathIcon className="w-3.5 h-3.5 animate-spin" />}
                      Re-run OCR
                    </button>
                    <button 
                      onClick={() => saveCleanMutation.mutate(localCleanText)} 
                      disabled={projectDetails?.status === '04_Synthesizing' || saveCleanMutation.isPending}
                      className="px-3 py-1.5 bg-white hover:bg-slate-50 text-slate-700 border border-slate-300 rounded-md text-xs font-semibold shadow-xs transition cursor-pointer flex items-center gap-1.5"
                    >
                      {saveCleanMutation.isPending && <ArrowPathIcon className="w-3.5 h-3.5 animate-spin"/>}
                      {saveCleanMutation.isPending ? 'Saving...' : 'Save Cleaned'}
                    </button>
                    <button 
                      onClick={() => runStageMutation.mutate(1)} 
                      disabled={projectDetails?.status === '04_Synthesizing' || runStageMutation.isPending}
                      className="px-3.5 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-md text-xs font-semibold shadow-xs transition cursor-pointer flex items-center gap-1.5 disabled:opacity-50"
                    >
                      {runStageMutation.isPending && <ArrowPathIcon className="w-3.5 h-3.5 animate-spin"/>}
                      {runStageMutation.isPending ? 'Segmenting...' : 'Run Segmentation →'}
                    </button>
                  </div>
                </div>
                <textarea 
                  className="flex-1 w-full p-4 font-mono text-xs text-slate-800 leading-relaxed resize-none focus:outline-none bg-white" 
                  value={localCleanText} 
                  onChange={(e) => setLocalCleanText(e.target.value)}
                  placeholder="Paste or edit text here..."
                />
              </div>
            </div>
          )}

          {/* ========================================================================= */}
          {/* STAGE 2: SEGMENTATION AUDIT (SIDE BY SIDE: CLEANED TEXT vs SEGMENTS) */}
          {/* ========================================================================= */}
          {currentStep === 2 && (
            <div className="flex flex-col lg:flex-row h-full gap-4">
              {/* Left Column: Cleaned Text for Reference / Upstream Modification */}
              <div className="w-full lg:w-2/5 bg-white rounded-xl shadow-xs border border-slate-200 overflow-hidden flex flex-col">
                <div className="bg-slate-50 px-4 py-2.5 border-b border-slate-200 flex justify-between items-center shrink-0">
                  <h2 className="text-xs font-bold uppercase text-slate-700">Cleaned Text Reference</h2>
                  <button 
                    onClick={() => saveCleanMutation.mutate(localCleanText)} 
                    disabled={projectDetails?.status === '04_Synthesizing' || saveCleanMutation.isPending}
                    className="px-2.5 py-1 bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 rounded text-xs font-medium cursor-pointer"
                  >
                    {saveCleanMutation.isPending ? 'Saving...' : 'Save Cleaned'}
                  </button>
                </div>
                <textarea 
                  className="flex-1 w-full p-3 font-mono text-xs text-slate-700 leading-relaxed resize-none focus:outline-none bg-slate-50/50" 
                  value={localCleanText} 
                  onChange={(e) => setLocalCleanText(e.target.value)}
                />
              </div>

              {/* Right Column: Interactive Segments Table */}
              <div className="flex-1 bg-white rounded-xl shadow-xs border border-slate-200 overflow-hidden flex flex-col">
                <div className="bg-slate-50 px-4 py-2.5 border-b border-slate-200 flex justify-between items-center shrink-0">
                  <div>
                    <h2 className="text-xs font-bold uppercase text-slate-800">Segmentation Audit ({activeSegments.length} Chunks)</h2>
                    <span className="text-[10px] text-slate-400 font-mono">03_segments.json</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <button 
                      onClick={() => saveSegmentsMutation.mutate(activeSegments)} 
                      disabled={projectDetails?.status === '04_Synthesizing' || saveSegmentsMutation.isPending || activeSegments.length === 0}
                      className="px-3 py-1.5 bg-white hover:bg-slate-50 text-slate-700 border border-slate-300 rounded-md text-xs font-semibold cursor-pointer flex items-center gap-1.5"
                    >
                      {saveSegmentsMutation.isPending && <ArrowPathIcon className="w-3.5 h-3.5 animate-spin"/>}
                      {saveSegmentsMutation.isPending ? 'Saving...' : 'Save Segments'}
                    </button>
                    <button 
                      onClick={() => runStageMutation.mutate(2)} 
                      disabled={projectDetails?.status === '04_Synthesizing' || runStageMutation.isPending || activeSegments.length === 0}
                      className="px-3.5 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-md text-xs font-semibold cursor-pointer flex items-center gap-1.5 disabled:opacity-50"
                    >
                      {runStageMutation.isPending && <ArrowPathIcon className="w-3.5 h-3.5 animate-spin"/>}
                      {runStageMutation.isPending ? 'Processing...' : 'Apply Phonetics →'}
                    </button>
                  </div>
                </div>

                {activeSegments.length === 0 ? (
                  <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-slate-500">
                    <p className="text-sm font-medium mb-3">No segments created yet.</p>
                    <button 
                      onClick={() => runStageMutation.mutate(1)} 
                      disabled={projectDetails?.status === '04_Synthesizing' || runStageMutation.isPending}
                      className="bg-blue-600 text-white px-4 py-2 rounded-lg text-xs font-semibold hover:bg-blue-700 transition"
                    >
                      {runStageMutation.isPending ? 'Running...' : 'Run Segmentation on Cleaned Text'}
                    </button>
                  </div>
                ) : (
                  <div className="overflow-y-auto flex-1 p-0">
                    <table className="min-w-full divide-y divide-slate-200 text-left text-xs">
                      <thead className="bg-slate-50 text-slate-500 sticky top-0 uppercase font-semibold">
                        <tr>
                          <th className="py-2.5 pl-4 pr-2 w-16">ID</th>
                          <th className="px-2 py-2.5 w-28">Type Tag</th>
                          <th className="px-3 py-2.5">Source Text</th>
                          <th className="px-2 py-2.5 w-24">Pause (ms)</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100 bg-white">
                        {activeSegments.map((seg, idx) => {
                          const updateSeg = (field, val) => {
                            const copy = [...activeSegments]
                            copy[idx] = { ...copy[idx], [field]: val }
                            setLocalSegments(copy)
                          }
                          return (
                            <tr key={seg.id || idx} className="hover:bg-slate-50/70 transition-colors">
                              <td className="py-2 pl-4 pr-2 font-mono text-[11px] text-slate-400 align-top">{seg.id}</td>
                              <td className="px-2 py-2 align-top">
                                <select 
                                  value={seg.segment_type || 'prose'} 
                                  onChange={(e) => updateSeg('segment_type', e.target.value)}
                                  className="w-full text-xs border border-slate-200 rounded px-1.5 py-1 bg-slate-50 focus:bg-white"
                                >
                                  {segmentTypes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                                </select>
                              </td>
                              <td className="px-3 py-2 align-top">
                                <textarea 
                                  rows={2} 
                                  value={seg.source_text || ''} 
                                  onChange={(e) => updateSeg('source_text', e.target.value)}
                                  className="w-full text-xs text-slate-800 border border-slate-200 rounded p-1.5 focus:border-blue-500 outline-none resize-y"
                                />
                              </td>
                              <td className="px-2 py-2 align-top">
                                <input 
                                  type="number" 
                                  value={seg.pause_after_ms !== undefined ? seg.pause_after_ms : 300} 
                                  onChange={(e) => updateSeg('pause_after_ms', parseInt(e.target.value) || 0)}
                                  className="w-full text-xs border border-slate-200 rounded p-1"
                                  title="Silence after this segment. Ordinary prose uses automatic punctuation pauses; use longer values for verses, stanzas and headings."
                                />
                                <span className="block text-[9px] text-slate-400 mt-1">0 = automatic · 300–500 ms = sentence · 800+ ms = stanza/heading</span>
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ========================================================================= */}
          {/* STAGE 3: PHONETIC SCRIPTING AUDIT (SIDE BY SIDE: SEGMENTS vs PHONETICS) */}
          {/* ========================================================================= */}
          {currentStep === 3 && (
            <div className="flex flex-col lg:flex-row h-full gap-4">
              {/* Left Column: Segments Reference */}
              <div className="w-full lg:w-2/5 bg-white rounded-xl shadow-xs border border-slate-200 overflow-hidden flex flex-col">
                <div className="bg-slate-50 px-4 py-2.5 border-b border-slate-200 flex justify-between items-center shrink-0">
                  <h2 className="text-xs font-bold uppercase text-slate-700">Segmentation Reference</h2>
                  <span className="text-[10px] text-slate-400 font-mono">03_segments.json</span>
                </div>
                <div className="overflow-y-auto flex-1 p-2 divide-y divide-slate-100">
                  {activeSegments.map((seg) => (
                    <div key={seg.id} className="py-2.5 px-2">
                      <div className="flex justify-between items-center mb-1">
                        <span className="font-mono text-[10px] text-slate-400">{seg.id}</span>
                        <span className="text-[10px] bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded uppercase font-semibold">{seg.segment_type}</span>
                      </div>
                      <p className="text-xs text-slate-800 leading-relaxed">{seg.source_text}</p>
                    </div>
                  ))}
                </div>
              </div>

              {/* Right Column: Phonetic Overrides Table */}
              <div className="flex-1 bg-white rounded-xl shadow-xs border border-slate-200 overflow-hidden flex flex-col">
                <div className="bg-slate-50 px-4 py-2.5 border-b border-slate-200 flex justify-between items-center shrink-0">
                  <div>
                    <h2 className="text-xs font-bold uppercase text-slate-800">Phonetics Scripting Audit</h2>
                    <span className="text-[10px] text-slate-400 font-mono">04_phonetics.json</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <button 
                      onClick={() => savePhoneticsMutation.mutate(activePhonetics)} 
                      disabled={projectDetails?.status === '04_Synthesizing' || savePhoneticsMutation.isPending || activePhonetics.length === 0}
                      className="px-3 py-1.5 bg-white hover:bg-slate-50 text-slate-700 border border-slate-300 rounded-md text-xs font-semibold cursor-pointer flex items-center gap-1.5"
                    >
                      {savePhoneticsMutation.isPending && <ArrowPathIcon className="w-3.5 h-3.5 animate-spin"/>}
                      {savePhoneticsMutation.isPending ? 'Saving...' : 'Save Phonetics'}
                    </button>
                    <button 
                      onClick={() => runStageMutation.mutate(3)} 
                      disabled={projectDetails?.status === '04_Synthesizing' || runStageMutation.isPending || savePhoneticsMutation.isPending || activePhonetics.length === 0}
                      className="px-3.5 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-md text-xs font-semibold cursor-pointer flex items-center gap-1.5 disabled:opacity-50"
                    >
                      {runStageMutation.isPending && <ArrowPathIcon className="w-3.5 h-3.5 animate-spin"/>}
                      {runStageMutation.isPending ? 'Synthesizing...' : savePhoneticsMutation.isPending ? 'Saving edits...' : 'Generate Audio →'}
                    </button>
                  </div>
                </div>

                {activePhonetics.length === 0 ? (
                  <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-slate-500">
                    <p className="text-sm font-medium mb-3">No phonetics generated yet.</p>
                    <button 
                      onClick={() => runStageMutation.mutate(2)} 
                      disabled={projectDetails?.status === '04_Synthesizing' || runStageMutation.isPending}
                      className="bg-blue-600 text-white px-4 py-2 rounded-lg text-xs font-semibold hover:bg-blue-700 transition"
                    >
                      Apply Pronunciation Rules to Segments
                    </button>
                  </div>
                ) : (
                  <div className="overflow-y-auto flex-1 p-0">
                    <table className="min-w-full divide-y divide-slate-200 text-left text-xs">
                      <thead className="bg-slate-50 text-slate-500 sticky top-0 uppercase font-semibold">
                        <tr>
                          <th className="py-2.5 pl-4 pr-2 w-16">ID</th>
                          <th className="px-3 py-2.5">Pronunciation Override</th>
                          <th className="px-2 py-2.5 w-20">Rate</th>
                          <th className="px-2 py-2.5 w-20">Pitch</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100 bg-white">
                        {activePhonetics.map((item, idx) => {
                          const updatePhon = (field, val) => {
                            const copy = [...activePhonetics]
                            copy[idx] = { ...copy[idx], [field]: val }
                            setLocalPhonetics(copy)
                          }
                          return (
                            <tr key={item.id || idx} className="hover:bg-slate-50/70 transition-colors">
                              <td className="py-2.5 pl-4 pr-2 font-mono text-[11px] text-slate-400 align-top">{item.id}</td>
                              <td className="px-3 py-2.5 align-top">
                                <textarea 
                                  rows={2} 
                                  value={item.pronunciation_text !== undefined ? item.pronunciation_text : item.source_text} 
                                  onChange={(e) => updatePhon('pronunciation_text', e.target.value)}
                                  className="w-full text-xs text-slate-900 border border-slate-200 rounded p-1.5 focus:border-blue-500 outline-none resize-y"
                                />
                              </td>
                              <td className="px-2 py-2.5 align-top">
                                <input 
                                  type="text" 
                                  value={item.rate || '+0%'} 
                                  onChange={(e) => updatePhon('rate', e.target.value)}
                                  className="w-full text-xs border border-slate-200 rounded p-1 font-mono"
                                  title="Relative speaking rate. -10% is slower and clearer but increases duration; +10% is faster and may reduce intelligibility."
                                />
                              </td>
                              <td className="px-2 py-2.5 align-top">
                                <input 
                                  type="text" 
                                  value={item.pitch || '+0Hz'} 
                                  onChange={(e) => updatePhon('pitch', e.target.value)}
                                  className="w-full text-xs border border-slate-200 rounded p-1 font-mono"
                                  title="Relative pitch. Small changes (about ±2 semitones) subtly deepen or brighten narration; larger changes may sound artificial. Provider units vary."
                                />
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ========================================================================= */}
          {/* STAGE 4: AUDIO REVIEW & MASTERING */}
          {/* ========================================================================= */}
          {currentStep === 4 && (
            <div className="bg-white rounded-xl shadow-xs border border-slate-200 overflow-hidden flex flex-col h-full">
              <div className="bg-slate-50 px-6 py-3 border-b border-slate-200 flex justify-between items-center shrink-0">
                <div>
                  <h2 className="text-sm font-bold text-slate-800">Audio Chunks Review</h2>
                  <p className="text-xs text-slate-500">Listen to synthesized speech chunks and master the full audiobook.</p>
                </div>
                <div className="flex items-center gap-2">
                  <button 
                    onClick={() => runStageMutation.mutate(4)} 
                    disabled={projectDetails?.status === '04_Synthesizing' || runStageMutation.isPending}
                    className="bg-green-600 hover:bg-green-700 text-white font-semibold px-4 py-2 rounded-lg text-xs transition cursor-pointer flex items-center gap-2 shadow-xs disabled:opacity-50"
                  >
                    <SpeakerWaveIcon className="w-4 h-4" />
                    {runStageMutation.isPending ? 'Mastering...' : 'Master Final Audiobook (Stage 4)'}
                  </button>
                </div>
              </div>

              {projectDetails?.status === '04_Synthesizing' ? (
                <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
                  <div className="w-16 h-16 rounded-2xl bg-indigo-50 text-indigo-600 flex items-center justify-center mb-4 animate-pulse">
                    <SpeakerWaveIcon className="w-8 h-8" />
                  </div>
                  <h3 className="text-base font-bold text-slate-900 mb-1">Synthesizing Speech Chunks</h3>
                  <p className="text-xs text-slate-500 max-w-sm mb-5 leading-relaxed">
                    Edge-TTS is generating 24kHz audio chunks for each sentence and verse. The waveform players will load automatically when ready.
                  </p>
                  <div className="w-full max-w-md bg-slate-100 rounded-full h-2.5 overflow-hidden mb-2">
                    <div 
                      className="bg-indigo-600 h-2.5 rounded-full transition-all duration-500 ease-out" 
                      style={{ width: `${Math.max(5, projectDetails?.audio_progress?.percent || 0)}%` }}
                    ></div>
                  </div>
                  <span className="text-xs font-semibold text-indigo-700">
                    {projectDetails?.audio_progress?.completed || 0} of {projectDetails?.audio_progress?.total || 0} chunks generated ({projectDetails?.audio_progress?.percent || 0}%)
                  </span>
                </div>
              ) : !projectDetails?.has_audio ? (
                <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-slate-500">
                  <SpeakerWaveIcon className="w-12 h-12 text-slate-300 mx-auto mb-3" />
                  <p className="text-sm font-medium text-slate-700 mb-1">No audio chunks generated yet</p>
                  <p className="text-xs text-slate-400 mb-4 max-w-sm">
                    Complete Stage 3 (Phonetic Scripting) and click "Generate Audio" to synthesize narration chunks.
                  </p>
                  <button 
                    onClick={() => setCurrentStep(3)}
                    className="bg-blue-600 hover:bg-blue-700 text-white font-semibold px-4 py-2 rounded-lg text-xs transition cursor-pointer"
                  >
                    ← Go to Stage 3: Phonetic Scripting
                  </button>
                </div>
              ) : (
                <div className="overflow-y-auto flex-1 divide-y divide-slate-100 p-2">
                  {activeSegments.map((seg) => (
                    <div key={seg.id} className="p-4 flex flex-col lg:flex-row lg:items-center justify-between gap-4 hover:bg-slate-50 rounded-lg transition-colors">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="font-mono text-xs text-slate-400">{seg.id}.wav</span>
                          <span className="text-[10px] bg-blue-50 text-blue-700 border border-blue-200 px-1.5 py-0.5 rounded uppercase font-semibold">
                            {seg.segment_type}
                          </span>
                        </div>
                        <p className="text-xs font-medium text-slate-800 leading-relaxed">{seg.source_text}</p>
                      </div>
                      <div className="w-full lg:w-96 shrink-0">
                        <WaveSurferPlayer url={`${API_BASE}/api/projects/${project}/audio/${seg.id}?token=${user?.token}`} />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* ========================================================================= */}
          {/* STAGE 5: MASTERED FINAL AUDIOBOOK */}
          {/* ========================================================================= */}
          {currentStep === 5 && (
            <div className="relative bg-white rounded-xl shadow-xs border border-slate-200 overflow-y-auto flex flex-col items-stretch justify-start p-6 text-center h-full">
              <div className="w-16 h-16 rounded-full bg-green-50 text-green-600 flex items-center justify-center mb-4">
                <CheckCircleIcon className="w-10 h-10" />
              </div>
              <h2 className="text-xl font-bold text-slate-900 mb-1">Audiobook Production Complete!</h2>
              <p className="text-xs text-slate-500 max-w-md mb-6">
                The final audiobook has been assembled and mastered. Listen through the result to verify pronunciation, pacing, and completeness before publishing.
              </p>

              <div className="w-full max-w-6xl lg:mr-96 flex flex-col gap-3 mb-6 text-left">
                <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-xs">
                  <div className="px-4 py-3 border-b border-slate-200 text-xs font-bold text-slate-700">Source PDF</div>
                  <iframe title="Source PDF for final review" src={pdfUrl} className="w-full h-[55vh] min-h-[420px]" />
                </div>

              {/* Mastered Audio Player */}
              <div className="w-full bg-slate-50 border border-slate-200 p-3 rounded-xl shadow-xs">
                <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-2">Mastered audio · review candidate</h3>
                <audio 
                  controls 
                  className="w-full"
                  ref={finalAudioRef}
                  onTimeUpdate={(e) => setReviewTimestamp(e.currentTarget.currentTime || 0)}
                  src={reviewData?.audio_url ? `${API_BASE}${reviewData.audio_url}?token=${user?.token}` : `${API_BASE}/api/projects/${project}/mastered?token=${user?.token}`}
                >
                  Your browser does not support the audio tag.
                </audio>
              </div>
              </div>

              <div className="w-full lg:absolute lg:right-6 lg:top-20 lg:w-80 grid grid-cols-1 gap-4 text-left mb-6">
                <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-xs">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider">Final editorial review</h3>
                    <span className={`text-[11px] font-semibold ${reviewData?.status === 'approved' ? 'text-green-600' : 'text-amber-600'}`}>
                      {reviewData ? reviewData.status.replace('_', ' ') : 'candidate pending review'}
                    </span>
                  </div>
                  <p className="text-xs text-slate-500 mb-3">Compare the PDF, transcript and audio above. Add a comment with a severity so corrections can return to the right stage.</p>
                  <div className="flex gap-2 mb-2">
                    <select value={reviewSeverity} onChange={(e) => setReviewSeverity(e.target.value)} className="text-xs border border-slate-200 rounded-md px-2 py-2">
                      <option value="blocker">Blocker</option><option value="major">Major</option><option value="minor">Minor</option>
                    </select>
         <textarea rows={3} value={reviewComment} onChange={(e) => setReviewComment(e.target.value)} placeholder={`What needs attention? (at ${Math.floor(reviewTimestamp / 60)}:${String(Math.floor(reviewTimestamp % 60)).padStart(2, '0')})`} className="flex-1 min-h-20 text-xs border border-slate-200 rounded-md px-2 py-2 resize-y focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none" />
                    <button disabled={!reviewComment.trim() || reviewIssueMutation.isPending} onClick={() => reviewIssueMutation.mutate()} className="px-3 py-2 rounded-md bg-slate-800 text-white text-xs font-semibold disabled:opacity-50">Add</button>
                  </div>
                  {reviewIssueMutation.isError && <p className="text-xs text-red-600 mb-2">{reviewIssueMutation.error.message}</p>}
                  <div className="space-y-2 max-h-36 overflow-y-auto">
                    {(reviewData?.issues || []).map(issue => <div key={issue.id} className="border-b border-slate-100 pb-2 text-xs"><span className={`font-semibold mr-2 ${issue.severity === 'blocker' ? 'text-red-600' : 'text-amber-600'}`}>{issue.severity}</span>{issue.body}<div className="flex items-center gap-2 mt-1"><span className="text-[10px] text-slate-400">{issue.status}</span>{(issue.status === 'open' || issue.status === 'reopened') && <button onClick={() => reviewIssueStatusMutation.mutate({ id: issue.id, status: 'resolved' })} className="text-[10px] text-green-700 font-semibold">Mark resolved</button>}</div></div>)}
                    {reviewData?.issues?.length === 0 && <p className="text-xs text-slate-400">No comments yet.</p>}
                  </div>
                </div>
                <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-xs flex flex-col justify-between">
       <div><h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-2">Decision</h3><p className="text-xs text-slate-500">Approval is tied to this exact mastered candidate. Two different human reviewers must approve before release.</p>{reviewData && <p className="text-xs font-semibold text-blue-700 mt-2">Human approvals: {reviewData.approval_count || 0} / {reviewData.required_approvals || 2}</p>}</div>
                  <div className="flex gap-2 mt-4">
                    <button onClick={() => reviewDecisionMutation.mutate('changes_requested')} disabled={!reviewData || reviewDecisionMutation.isPending} className="flex-1 px-3 py-2 rounded-md border border-amber-300 text-amber-700 text-xs font-semibold disabled:opacity-50">Request changes</button>
                    <button onClick={() => reviewDecisionMutation.mutate('approved')} disabled={!reviewData || reviewData.open_blockers > 0 || reviewDecisionMutation.isPending} className="flex-1 px-3 py-2 rounded-md bg-green-600 text-white text-xs font-semibold disabled:opacity-50">Approve candidate</button>
                  </div>
                  {reviewData?.open_blockers > 0 && <p className="text-[11px] text-red-600 mt-2">Resolve {reviewData.open_blockers} blocking issue(s) before approval.</p>}
                  {reviewDecisionMutation.isError && <p className="text-xs text-red-600 mt-2">{reviewDecisionMutation.error.message}</p>}
                </div>
              </div>

              <div className="flex gap-4">
                <a 
                  href={`${API_BASE}/api/projects/${project}/mastered?token=${user?.token}`}
                  download 
                  className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-blue-600 text-white text-xs font-bold hover:bg-blue-700 shadow-xs transition cursor-pointer"
                >
                  <ArrowDownTrayIcon className="w-4 h-4" /> Download Complete Audiobook (.mp3)
                </a>
                <Link 
                  to="/dashboard"
                  className="inline-flex items-center px-4 py-2.5 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-bold transition cursor-pointer"
                >
                  Back to Dashboard
                </Link>
              </div>
            </div>
          )}

        </main>
      </div>

      {/* ========================================================================= */}
      {/* ARTIFACTS & AUDIT MODAL */}
      {/* ========================================================================= */}
      {showArtifactsModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4 sm:p-6 animate-in fade-in duration-200">
          <div className="bg-white rounded-2xl shadow-2xl border border-slate-200 max-w-4xl w-full flex flex-col max-h-[85vh] overflow-hidden">
            <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between bg-slate-50 shrink-0">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-xl bg-blue-100 text-blue-700 flex items-center justify-center">
                  <FolderIcon className="w-5 h-5" />
                </div>
                <div>
                  <h2 className="text-sm font-bold text-slate-900">Project Artifacts & Audit History</h2>
                  <p className="text-xs text-slate-500">Every pipeline stage writes an immutable, timestamped artifact with editor attribution to the database</p>
                </div>
              </div>
              <button
                onClick={() => setShowArtifactsModal(false)}
                className="text-slate-400 hover:text-slate-600 p-1.5 rounded-lg hover:bg-slate-200/50 transition cursor-pointer text-sm font-bold"
              >
                ✕
              </button>
            </div>

            <div className="p-6 overflow-y-auto flex-1">
              {artifactsList.length === 0 ? (
                <div className="text-center py-12 text-slate-400 text-xs">
                  No artifacts generated yet. Run pipeline stages to create saved artifacts.
                </div>
              ) : (
                <div className="border border-slate-200 rounded-xl overflow-hidden shadow-2xs">
                  <table className="w-full text-left text-xs border-collapse">
                    <thead>
                      <tr className="bg-slate-50 text-slate-500 font-semibold border-b border-slate-200">
                        <th className="py-2.5 px-4">Artifact Filename</th>
                        <th className="py-2.5 px-3">Stage</th>
                        <th className="py-2.5 px-3">Editor</th>
                        <th className="py-2.5 px-3">Timestamp</th>
                        <th className="py-2.5 px-3">Size</th>
                        <th className="py-2.5 px-3 text-right">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {artifactsList.map((art) => (
                        <tr key={art.id} className="hover:bg-slate-50/80 transition-colors">
                          <td className="py-2.5 px-4 font-mono font-medium text-slate-800 break-all">
                            {art.filename}
                          </td>
                          <td className="py-2.5 px-3">
                            <span className="px-2 py-0.5 rounded bg-blue-50 text-blue-700 text-[10px] font-semibold uppercase">
                              {art.stage}
                            </span>
                          </td>
                          <td className="py-2.5 px-3 text-slate-600 font-medium">
                            {art.username || 'system'}
                          </td>
                          <td className="py-2.5 px-3 text-slate-500 font-mono text-[11px]">
                            {art.created_at ? new Date(art.created_at).toLocaleString() : '—'}
                          </td>
                          <td className="py-2.5 px-3 text-slate-500 font-mono text-[11px]">
                            {art.file_size > 1024 * 1024
                              ? `${(art.file_size / (1024 * 1024)).toFixed(1)} MB`
                              : `${Math.round(art.file_size / 1024)} KB`}
                          </td>
                          <td className="py-2.5 px-3 text-right">
                            {(art.file_type === 'txt' || art.file_type === 'json') && (
                              <button onClick={() => restoreArtifactMutation.mutate(art.filename)} disabled={restoreArtifactMutation.isPending} className="inline-flex items-center gap-1 px-2.5 py-1 mr-2 rounded-md bg-amber-50 hover:bg-amber-100 text-amber-700 text-[11px] font-semibold disabled:opacity-50">Load as draft</button>
                            )}
                            <a
                              href={`${API_BASE}${art.download_url}?token=${user?.token}`}
                              download
                              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-slate-100 hover:bg-blue-50 text-slate-700 hover:text-blue-700 text-[11px] font-semibold transition cursor-pointer"
                            >
                              <ArrowDownTrayIcon className="w-3 h-3" /> Download
                            </a>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div className="px-6 py-3 bg-slate-50 border-t border-slate-200 flex justify-end shrink-0">
              <button
                onClick={() => setShowArtifactsModal(false)}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-900 text-white rounded-lg text-xs font-semibold transition cursor-pointer"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default ProjectPipeline
