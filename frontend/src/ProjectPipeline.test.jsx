import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import ProjectPipeline from './ProjectPipeline'
import { AuthContext } from './AuthContext'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

describe('ProjectPipeline', () => {
  let queryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    
    // Mock fetch
    global.fetch = vi.fn((url) => {
      if (url.includes('/api/projects/test_book/raw')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ raw_text: 'Sample text', clean_text: 'Cleaned text', text: 'Cleaned text', has_clean: true })
        });
      }
      if (url.includes('/api/projects/test_book/segments')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([{ id: '001', source_text: 'Cleaned text', segment_type: 'prose', pause_after_ms: 300 }])
        });
      }
      if (url.includes('/api/projects/test_book/phonetics')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([{ id: '001', pronunciation_text: 'Cleaned text', rate: '+0%', pitch: '+0Hz' }])
        });
      }
      if (url.includes('/api/projects/test_book/artifacts')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([])
        });
      }
      if (url.includes('/api/projects/test_book/stage/all') || url.match(/\/api\/projects\/test_book\/stage\/\d+/)) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ status: 'success', new_status: '04_Synthesizing' })
        });
      }
      // Default project details
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          id: 1, name: 'test_book', status: '00_Ingested', assigned_username: 'testeditor', has_raw_text: false, has_clean_text: false, has_segments: false, has_phonetics: false, has_audio: false, has_mastered: false, audio_progress: { completed: 0, total: 0, percent: 0 }
        })
      });
    });
  })

  afterEach(() => {
    vi.restoreAllMocks();
    queryClient.clear();
  });

  const renderComponent = () => {
    const user = { username: 'testeditor', token: 'fake-token', role: 'editor' }
    return render(
      <QueryClientProvider client={queryClient}>
        <AuthContext.Provider value={{ user }}>
          <MemoryRouter initialEntries={['/project/test_book']}>
            <Routes>
              <Route path="/project/:id" element={<ProjectPipeline />} />
            </Routes>
          </MemoryRouter>
        </AuthContext.Provider>
      </QueryClientProvider>
    )
  }

  it('renders pipeline workspace with stage navigation', async () => {
    renderComponent()
    
    expect(await screen.findByText('test_book')).toBeInTheDocument()
    expect(screen.getByText(/PDF Ingestion/i)).toBeInTheDocument()
    expect(screen.getByText(/Force Recompute/i)).toBeInTheDocument()
    expect(screen.getByText(/Run All Stages/i)).toBeInTheDocument()
  })

  it('supports Run All stages functionality', async () => {
    renderComponent()
    
    const runAllBtn = await screen.findByText(/Run All Stages/i)
    fireEvent.click(runAllBtn)
    
    await waitFor(() => {
      // It should call the stage/all endpoint
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/projects/test_book/stage/all'),
        expect.objectContaining({ method: 'POST' })
      )
    })
  })

  it('supports Force Recompute checkbox parameter passing', async () => {
    renderComponent()
    
    // Check force recompute
    const forceCheckbox = await screen.findByLabelText(/Force Recompute/i)
    fireEvent.click(forceCheckbox)
    expect(forceCheckbox.checked).toBe(true)

    // Trigger Run OCR (stage 0 runs stage 1 endpoint)
    const runOcrBtn = await screen.findByRole('button', { name: /Run OCR Extraction/i })
    fireEvent.click(runOcrBtn)

    await waitFor(() => {
      // Verify force=true is in URL
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/projects/test_book/stage/1?force=true'),
        expect.objectContaining({ method: 'POST' })
      )
    })
  })

  it('automatically progresses through manual stages correctly', async () => {
    renderComponent()
    
    // Initial state is Stage 0
    const runOcrBtn = await screen.findByRole('button', { name: /Run OCR Extraction/i })
    fireEvent.click(runOcrBtn)
    
    // Next state is Stage 1 -> Text Refinement
    await waitFor(() => {
      expect(screen.getAllByText(/Run Segmentation →/i).length).toBeGreaterThan(0)
    })
  })
})
