import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import LogViewer from './pages/LogViewer'
import SSHConfigPage from './pages/SSHConfigPage'
import WorkspaceConfigPage from './pages/WorkspaceConfigPage'
import AIConfigPage from './pages/AIConfigPage'
import FilePushPage from './pages/FilePushPage'
import { useWebSocket } from './hooks/useWebSocket'

function App() {
  useWebSocket()

  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/logs" element={<LogViewer />} />
          <Route path="/config/ssh" element={<SSHConfigPage />} />
          <Route path="/config/workspace" element={<WorkspaceConfigPage />} />
          <Route path="/config/ai" element={<AIConfigPage />} />
          <Route path="/tools/push" element={<FilePushPage />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  )
}

export default App
