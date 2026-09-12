import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import Dashboard from './Dashboard'
import { AuthContext } from './AuthContext'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

const queryClient = new QueryClient({
    defaultOptions: {
        queries: {
            retry: false,
        },
    },
})

describe('Dashboard Component', () => {
  it('renders standard empty state when no projects exist', () => {
    // Mock user
    const user = { username: 'testuser', token: 'fake', role: 'editor' }
    const logout = vi.fn()
    console.log("Dashboard is:", Dashboard);

    // We can't easily mock useQuery here without msw, but for now 
    // let's just assert the basic shell renders
    render(
      <QueryClientProvider client={queryClient}>
        <AuthContext.Provider value={{ user, logout }}>
          <MemoryRouter>
            <Dashboard />
          </MemoryRouter>
        </AuthContext.Provider>
      </QueryClientProvider>
    )

    expect(screen.getByText(/AWGP Audiobook Production/i)).toBeInTheDocument()
    expect(screen.getByText(/testuser/i)).toBeInTheDocument()
  })
})
