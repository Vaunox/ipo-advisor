import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The renderer talks to the advisory engine over its GET-only API.
// - dev: Vite proxies /api -> the local FastAPI engine (runner default port 8000).
// - Electron: the shell injects window.__ENGINE_BASE__ = http://127.0.0.1:<free-port>
//   (see the client), so the same build works against the sidecar's chosen port.
export default defineConfig({
  plugins: [react()],
  base: './', // relative asset paths so the bundle loads from file:// inside Electron
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
    },
  },
})
