import { useState, useEffect } from 'react'

function App() {
  const [status, setStatus] = useState<string>('Loading...')

  useEffect(() => {
    fetch('/api/health')
      .then(res => res.json())
      .then(data => setStatus(data.status))
      .catch(() => setStatus('Error'))
  }, [])

  return (
    <div className="min-h-screen bg-gray-900 text-white flex items-center justify-center">
      <div className="text-center">
        <h1 className="text-4xl font-bold mb-4">Code Sonar</h1>
        <p className="text-xl text-gray-400 mb-2">Credit report for your codebase</p>
        <p className="text-sm text-gray-500">API Status: {status}</p>
      </div>
    </div>
  )
}

export default App
