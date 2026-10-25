import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Бэкенд по CONTRACT.md, раздел 6
const BACKEND = 'http://localhost:8000'

const proxy = {
  '/api': { target: BACKEND, changeOrigin: true },
  '/ws': { target: BACKEND, changeOrigin: true, ws: true },
  '/media': { target: BACKEND, changeOrigin: true },
  '/hls': { target: BACKEND, changeOrigin: true },
}

export default defineConfig({
  plugins: [react()],
  base: '/',
  server: {
    port: 5173,
    proxy,
  },
  preview: {
    port: 4173,
    proxy,
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
