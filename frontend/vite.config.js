import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      '/webhook': {
        target: 'http://localhost:5678',
        changeOrigin: true,
      },
      '/webhook-test': {
        target: 'http://localhost:5678',
        changeOrigin: true,
      },
    },
  },
})
