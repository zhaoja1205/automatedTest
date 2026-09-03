import { useState } from 'react'
import { Layout as AntLayout, Menu, Badge } from 'antd'
import {
  ExperimentOutlined,
  FileTextOutlined,
  RobotOutlined,
  CloudUploadOutlined,
  ApiOutlined,
  FolderOpenOutlined,
} from '@ant-design/icons'
import { useNavigate, useLocation } from 'react-router-dom'
import { useStore } from '../stores/useStore'

const { Sider, Content } = AntLayout

const HEADER_TABS = [
  { key: 'test', label: '运行测试' },
  { key: 'report', label: '记录报告' },
]

const SIDER_MENUS = [
  { key: '/', icon: <ExperimentOutlined />, label: '测试执行' },
  { key: '/logs', icon: <FileTextOutlined />, label: '执行日志' },
  { key: 'divider-config', type: 'divider' as const },
  { key: '/config/ssh', icon: <ApiOutlined />, label: 'SSH 连接' },
  { key: '/config/workspace', icon: <FolderOpenOutlined />, label: '工作区配置' },
  { key: '/config/ai', icon: <RobotOutlined />, label: 'AI 配置' },
  { key: 'divider-tools', type: 'divider' as const },
  { key: '/tools/push', icon: <CloudUploadOutlined />, label: '文件推送' },
]

export default function Layout({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate()
  const location = useLocation()
  const store = useStore()
  const [collapsed, setCollapsed] = useState(false)
  const [activeTab] = useState('test')

  const sshStatusDot = store.sshStatus?.connected
    ? 'success' as const
    : store.sshStatus?.tested
      ? 'error' as const
      : 'default' as const

  const selectedKey = (() => {
    const path = location.pathname
    if (path === '/' || path === '') return '/'
    if (path === '/logs') return '/logs'
    if (path.startsWith('/config/ssh')) return '/config/ssh'
    if (path.startsWith('/config/workspace')) return '/config/workspace'
    if (path.startsWith('/config/ai')) return '/config/ai'
    if (path.startsWith('/tools/push')) return '/tools/push'
    return '/'
  })()

  return (
    <AntLayout style={{ minHeight: '100vh' }}>
      {/* ===== 顶部 Header（白底 + 底部细线） ===== */}
      <div className="app-header">
        <div className="header-brand">
          <div className="header-brand-icon">
            <ExperimentOutlined />
          </div>
          <span className="header-brand-text">测试管理</span>
        </div>
        <div className="header-nav">
          {HEADER_TABS.map(tab => (
            <div
              key={tab.key}
              className={`header-nav-item ${activeTab === tab.key ? 'active' : ''}`}
            >
              {tab.label}
            </div>
          ))}
        </div>
        <div className="header-right">
          <Badge status={sshStatusDot} text={
            <span style={{ fontSize: 12, color: '#5e6c84' }}>
              {store.sshStatus?.connected ? 'SSH 已连接' : 'SSH 未连接'}
            </span>
          } />
          <Badge status={store.isConnected ? 'success' : 'error'} text={
            <span style={{ fontSize: 12, color: '#5e6c84' }}>
              {store.isConnected ? 'WS 已连接' : 'WS 未连接'}
            </span>
          } />
        </div>
      </div>

      <AntLayout>
        {/* ===== 左侧 Sider（白底 + 右侧细线） ===== */}
        <Sider
          collapsible
          collapsed={collapsed}
          onCollapse={setCollapsed}
          width={180}
          collapsedWidth={56}
          className={`app-sider ${collapsed ? 'sider-collapsed' : ''}`}
          theme="light"
        >
          <div className="sider-logo">
            <ExperimentOutlined className="logo-icon" />
            <span className="logo-text">功能导航</span>
          </div>
          <Menu
            mode="inline"
            selectedKeys={[selectedKey]}
            items={SIDER_MENUS}
            onClick={({ key }) => {
              if (!key.startsWith('divider')) navigate(key)
            }}
          />
        </Sider>

        {/* ===== 内容区 ===== */}
        <Content className="page-content">
          {children}
        </Content>
      </AntLayout>
    </AntLayout>
  )
}
