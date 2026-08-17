import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import LogViewer from './pages/LogViewer'
import { useWebSocket } from './hooks/useWebSocket'

function App() {
  useWebSocket()

  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/logs" element={<LogViewer />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  )
}

export default App