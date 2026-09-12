import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import ProjectPipeline from './ProjectPipeline'
import { AuthContext } from './AuthContext'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
    },
  },
})

describe('ProjectPipeline', () => {
  it('renders pipeline workspace with stage navigation', () => {
    const user = { username: 'testeditor', token: 'fake-token', role: 'editor' }
    render(
      <QueryClientProvider client={queryClient}>
        <AuthContext.Provider value={{ user }}>
          <MemoryRouter initialEntries={['/project/brahma_sandhya']}>
            <Routes>
              <Route path="/project/:id" element={<ProjectPipeline />} />
            </Routes>
          </MemoryRouter>
        </AuthContext.Provider>
      </QueryClientProvider>
    )
    expect(screen.getByText('brahma_sandhya')).toBeInTheDocument()
    expect(screen.getByText(/PDF Ingestion/i)).toBeInTheDocument()
    expect(screen.getAllByText(/Text Refinement/i).length).toBeGreaterThan(0)
    expect(screen.getByText(/Optical Character Recognition/i)).toBeInTheDocument()
  })
})
