import { API_BASE } from './config'
import { useState, useContext } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { AuthContext } from './AuthContext';

function Register() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [recordingType, setRecordingType] = useState('AI audiobook narration');
  const [language, setLanguage] = useState('Hindi');
  const { login } = useContext(AuthContext);
  const navigate = useNavigate();

  const handleRegister = async (e) => {
    e.preventDefault();
    const res = await fetch(`${API_BASE}/api/signup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password, full_name: fullName, email, phone, recording_type: recordingType, language })
    });
    const data = await res.json();
    if (res.ok) {
      login(data); // Auto-login after register
      navigate('/dashboard');
    } else {
      alert(data.detail || 'Registration failed');
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-md w-full space-y-8 bg-white p-8 rounded-xl shadow-sm border border-slate-200">
        <div>
          <h2 className="mt-6 text-center text-3xl font-extrabold text-slate-900">Register new account</h2>
          <p className="mt-2 text-center text-sm text-slate-500">Register as an editor volunteer. An administrator will allocate a book after reviewing your details.</p>
        </div>
        <form className="mt-8 space-y-6" onSubmit={handleRegister}>
          <div className="rounded-md shadow-sm -space-y-px">
            <input name="full_name" type="text" required className="appearance-none rounded-none relative block w-full px-3 py-2 border border-slate-300 text-slate-900 rounded-t-md focus:outline-none focus:ring-blue-500 focus:border-blue-500 sm:text-sm" placeholder="Full name" value={fullName} onChange={e => setFullName(e.target.value)} />
            <input name="email" type="email" required className="appearance-none rounded-none relative block w-full px-3 py-2 border border-slate-300 text-slate-900 focus:outline-none focus:ring-blue-500 focus:border-blue-500 sm:text-sm" placeholder="Email address" value={email} onChange={e => setEmail(e.target.value)} />
            <input name="phone" type="tel" required className="appearance-none rounded-none relative block w-full px-3 py-2 border border-slate-300 text-slate-900 focus:outline-none focus:ring-blue-500 focus:border-blue-500 sm:text-sm" placeholder="Phone / WhatsApp number" value={phone} onChange={e => setPhone(e.target.value)} />
            <div>
              <input name="username" type="text" required className="appearance-none rounded-none relative block w-full px-3 py-2 border border-slate-300 placeholder-slate-500 text-slate-900 rounded-t-md focus:outline-none focus:ring-blue-500 focus:border-blue-500 focus:z-10 sm:text-sm" placeholder="Username" value={username} onChange={e => setUsername(e.target.value)} />
            </div>
            <div>
              <input name="password" type="password" required className="appearance-none rounded-none relative block w-full px-3 py-2 border border-slate-300 placeholder-slate-500 text-slate-900 focus:outline-none focus:ring-blue-500 focus:border-blue-500 focus:z-10 sm:text-sm" placeholder="Password" value={password} onChange={e => setPassword(e.target.value)} />
            </div>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <select value={recordingType} onChange={e => setRecordingType(e.target.value)} className="rounded-md border border-slate-300 px-3 py-2 text-sm bg-white"><option>AI audiobook narration</option><option>Quality audit / review</option></select>
            <select value={language} onChange={e => setLanguage(e.target.value)} className="rounded-md border border-slate-300 px-3 py-2 text-sm bg-white"><option>Hindi</option><option>Sanskrit</option><option>Hindi + Sanskrit</option></select>
          </div>
          <div>
            <button type="submit" className="group relative w-full flex justify-center py-2 px-4 border border-transparent text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500">Register</button>
          </div>
          <div className="text-center text-sm">
            <Link to="/login" className="font-medium text-blue-600 hover:text-blue-500">Already have an account? Login</Link>
          </div>
        </form>
      </div>
    </div>
  );
}

export default Register;
