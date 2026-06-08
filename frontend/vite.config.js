import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8080'
const apiProxy = {
  '/api': {
    target: apiProxyTarget,
    changeOrigin: true
  }
}

export default defineConfig({
  plugins: [vue()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) {
            return undefined
          }
          if (id.includes('element-plus') || id.includes('@element-plus') || id.includes('@popperjs')) {
            return 'element-plus'
          }
          if (id.includes('@vue') || id.includes('/vue/')) {
            return 'vue'
          }
          if (id.includes('markdown-it') || id.includes('dompurify')) {
            return 'markdown'
          }
          if (id.includes('axios')) {
            return 'http'
          }
          return 'vendor'
        }
      }
    }
  },
  server: {
    port: 5173,
    proxy: apiProxy
  },
  preview: {
    proxy: apiProxy
  }
})
