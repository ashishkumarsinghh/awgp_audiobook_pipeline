import React from 'react'
import { ExclamationTriangleIcon, ArrowPathIcon } from '@heroicons/react/24/solid'

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-slate-50 flex items-center justify-center p-6">
          <div className="max-w-md w-full bg-white rounded-2xl shadow-xl border border-rose-100 p-8 text-center space-y-4">
            <div className="w-14 h-14 bg-rose-50 text-rose-600 rounded-2xl mx-auto flex items-center justify-center border border-rose-100 shadow-xs">
              <ExclamationTriangleIcon className="w-8 h-8" />
            </div>
            <h2 className="text-xl font-bold text-slate-800">Something went wrong</h2>
            <p className="text-xs text-rose-600 bg-rose-50 p-3 rounded-lg font-mono text-left overflow-auto max-h-32 border border-rose-100">
              {this.state.error?.message || 'An unexpected error occurred'}
            </p>
            <div className="pt-2 flex gap-3 justify-center">
              <button
                onClick={() => window.location.href = '/dashboard'}
                className="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold rounded-lg transition-colors"
              >
                Go to Dashboard
              </button>
              <button
                onClick={() => window.location.reload()}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold rounded-lg transition-colors flex items-center gap-1.5 shadow-sm shadow-blue-500/20"
              >
                <ArrowPathIcon className="w-3.5 h-3.5" /> Reload Page
              </button>
            </div>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}

export default ErrorBoundary
