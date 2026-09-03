import React from 'react'
import ReactDOM from 'react-dom/client'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#2f54eb',
          colorBgLayout: '#f4f5f7',
          borderRadius: 4,
          colorLink: '#2f54eb',
          colorLinkHover: '#1d39c4',
          fontSize: 13,
        },
        components: {
          Menu: {
            itemBg: 'transparent',
            itemColor: '#42526e',
            itemHoverColor: '#2f54eb',
            itemHoverBg: '#e8ecf4',
            itemSelectedColor: '#2f54eb',
            itemSelectedBg: '#e8ecf4',
            iconSize: 15,
            itemHeight: 38,
          },
          Table: {
            headerBg: '#fafbfc',
            headerColor: '#5e6c84',
            headerSortActiveBg: '#ebecf0',
            rowHoverBg: '#fafbfc',
            cellPaddingBlockSM: 8,
          },
          Card: {
            headerFontSize: 14,
            paddingLG: 16,
          },
          Button: {
            borderRadius: 4,
          },
        },
      }}
    >
      <App />
    </ConfigProvider>
  </React.StrictMode>,
)
