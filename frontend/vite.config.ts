import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import basicSsl from '@vitejs/plugin-basic-ssl'

// 用 env 开关 HTTPS 自签：
//   npm run dev               → http   (默认，不影响老 workflow)
//   VITE_HTTPS=1 npm run dev  → https  (自签证书，供 showDirectoryPicker 用)
const enableHttps = process.env.VITE_HTTPS === '1'

export default defineConfig({
  plugins: [
    react(),
    ...(enableHttps ? [basicSsl()] : []),
  ],
  server: {
    host: '0.0.0.0',
    port: 3000,
    strictPort: true,
    https: enableHttps ? {} : undefined,   // basicSsl() 会注入真正的 key/cert
    watch: {
      usePolling: true,
      interval: 300,
    },
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
})
