import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const projectRoot = path.dirname(fileURLToPath(import.meta.url))

// Split the heaviest third-party code out of the app bundle. Vite 8 bundles
// with Rolldown, whose `manualChunks` takes a function rather than the object
// map Rollup accepted, so the grouping is expressed as a lookup.
const CHUNK_GROUPS: Record<string, string[]> = {
  vendor: ['react', 'react-dom', 'react-router-dom'],
  ui: [
    'lucide-react',
    '@radix-ui/react-avatar',
    '@radix-ui/react-dropdown-menu',
    '@radix-ui/react-slot',
  ],
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.VITE_BACKEND_URL || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: process.env.VITE_BACKEND_WS_URL || 'ws://127.0.0.1:8000',
        ws: true,
        changeOrigin: true,
      },
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(projectRoot, './src'),
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return
          for (const [chunk, packages] of Object.entries(CHUNK_GROUPS)) {
            if (packages.some((pkg) => id.includes(`node_modules/${pkg}/`))) {
              return chunk
            }
          }
        },
      },
    },
  },
})
