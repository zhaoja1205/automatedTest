import { Layout as AntLayout, Menu, Typography } from 'antd'
import { ExperimentOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'

const { Header, Content } = AntLayout

export default function Layout({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate()

  return (
    <AntLayout style={{ minHeight: '100vh' }}>
      <Header style={{ display: 'flex', alignItems: 'center', padding: '0 24px' }}>
        <ExperimentOutlined style={{ fontSize: 24, color: '#fff', marginRight: 12 }} />
        <Typography.Title level={4} style={{ color: '#fff', margin: 0 }}>
          测试执行管理系统
        </Typography.Title>
        <Menu
          theme="dark"
          mode="horizontal"
          style={{ flex: 1, marginLeft: 24 }}
          items={[
            { key: '/', label: '测试执行', icon: <ExperimentOutlined /> },
          ]}
          onClick={({ key }) => navigate(key)}
        />
      </Header>
      <Content style={{ padding: 24 }}>
        {children}
      </Content>
    </AntLayout>
  )
}