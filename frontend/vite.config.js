import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:43181'
const apiProxy = {
  '/api': {
    target: apiProxyTarget,
    changeOrigin: true
  }
}

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: apiProxy
  },
  preview: {
    proxy: apiProxy
  }
})
