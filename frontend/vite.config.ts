import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { configDefaults } from 'vitest/config'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, 'src') },
  },
  server: {
    proxy: {
      '/api': { target: process.env.HERACLES_API_URL ?? 'http://localhost:8420', changeOrigin: true },
    },
  },
  build: {
    chunkSizeWarningLimit: 900,
    // Never inline fonts as data: URIs; the server CSP only allows font-src 'self'.
    assetsInlineLimit: (file) => (/\.(woff2?|ttf|otf)$/.test(file) ? false : undefined),
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    testTimeout: 20000,
    // browser end-to-end specs run with Playwright against a live stack
    exclude: [...configDefaults.exclude, 'e2e/**'],
  },
})
