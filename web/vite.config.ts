import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/health/ingestion': { target: 'http://localhost:8000', rewrite: () => '/health' },
      '/health/demo-app': { target: 'http://localhost:8001', rewrite: () => '/health' },
      '/health': { target: 'http://localhost:8002' },
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
})
