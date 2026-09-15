import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'
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
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      injectRegister: 'script',
      workbox: {
        // The webmanifest is precached automatically by the plugin.
        globPatterns: ['**/*.{js,css,html,png,svg,jpg,jpeg,webp,ico,woff2,txt}'],
        globIgnores: ['**/og-image*', '**/vite.svg'],
        navigateFallback: '/index.html',
        // nginx already falls back to index.html for unknown paths; the
        // denylist just keeps API and WebSocket requests out of the fallback.
        navigateFallbackDenylist: [/^\/_/, /^\/api\//, /^\/ws\//, /\/[^/?]+\.[^/]+$/],
        cleanupOutdatedCaches: true,
        maximumFileSizeToCacheInBytes: 5 * 1024 * 1024,
        runtimeCaching: [
          {
            urlPattern: /^https:\/\/fonts\.googleapis\.com\/.*/i,
            handler: 'CacheFirst',
            options: {
              cacheName: 'google-fonts-stylesheets',
              expiration: { maxEntries: 5, maxAgeSeconds: 60 * 60 * 24 * 365 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
          {
            urlPattern: /^https:\/\/fonts\.gstatic\.com\/.*/i,
            handler: 'CacheFirst',
            options: {
              cacheName: 'google-fonts-webfonts',
              expiration: { maxEntries: 10, maxAgeSeconds: 60 * 60 * 24 * 365 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
        ],
      },
    }),
  ],
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
