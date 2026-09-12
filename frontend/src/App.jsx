import { useContext } from 'react'
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom'
import Dashboard from './Dashboard'
import ProjectPipeline from './ProjectPipeline'
import Login from './Login'
import Register from './Register'
import Home from './Home'
import ErrorBoundary from './ErrorBoundary'
import { AuthContext } from './AuthContext'

function ProtectedRoute({ children }) {
  const { user } = useContext(AuthContext);
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

function App() {
  const { user } = useContext(AuthContext);

  return (
    <ErrorBoundary>
      <Router>
        <Routes>
          <Route path="/" element={user ? <Navigate to="/dashboard" replace /> : <Home />} />
          <Route path="/projects" element={<Navigate to="/dashboard" replace />} />
          <Route path="/login" element={user ? <Navigate to="/dashboard" replace /> : <Login />} />
          <Route path="/register" element={user ? <Navigate to="/dashboard" replace /> : <Register />} />
          <Route path="/dashboard" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
          <Route path="/project/:id" element={<ProtectedRoute><ProjectPipeline /></ProtectedRoute>} />
        </Routes>
      </Router>
    </ErrorBoundary>
  )
}

export default App
