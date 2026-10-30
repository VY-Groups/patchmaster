import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev has no nginx: mirror frontend/nginx.conf (/api, /download -> backend) so
// appRuntime.js's same-origin resolution for port 3000 actually reaches the API.
const apiTarget = process.env.API_PROXY_TARGET || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    host: true,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true, ws: true },
      '/download': {
        target: apiTarget,
        changeOrigin: true,
        rewrite: (path) => '/static' + path.slice('/download'.length),
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            return 'vendor';
          }
          if (id.includes('/src/') && /OpsPage|TestingPage/.test(id)) {
            return 'workspace-pages';
          }
        }
      }
    }
  }
})
