import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import LogViewer from './pages/LogViewer'
import SSHConfigPage from './pages/SSHConfigPage'
import WorkspaceConfigPage from './pages/WorkspaceConfigPage'
import AIConfigPage from './pages/AIConfigPage'
import CleanupConfigPage from './pages/CleanupConfigPage'
import FilePushPage from './pages/FilePushPage'
import ExecutionHistoryPage from './pages/ExecutionHistoryPage'
import RunDetailPage from './pages/RunDetailPage'
import RunComparePage from './pages/RunComparePage'
import ReportsPage from './pages/ReportsPage'
import ReportViewPage from './pages/ReportViewPage'
import { useWebSocket } from './hooks/useWebSocket'

function App() {
  useWebSocket()

  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          {/* 运行测试模块 */}
          <Route path="/" element={<Dashboard />} />
          <Route path="/logs" element={<LogViewer />} />
          <Route path="/config/ssh" element={<SSHConfigPage />} />
          <Route path="/config/workspace" element={<WorkspaceConfigPage />} />
          <Route path="/config/ai" element={<AIConfigPage />} />
          <Route path="/config/cleanup" element={<CleanupConfigPage />} />
          <Route path="/tools/push" element={<FilePushPage />} />
          {/* 记录报告模块 */}
          <Route path="/records/runs" element={<ExecutionHistoryPage />} />
          <Route path="/records/runs/:runId" element={<RunDetailPage />} />
          <Route path="/records/compare" element={<RunComparePage />} />
          <Route path="/records/reports" element={<ReportsPage />} />
          <Route path="/records/reports/:reportId" element={<ReportViewPage />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  )
}

export default App
