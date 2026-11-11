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
    // Budget for a single chunk (minified); pages are loaded per route (src/router.tsx).
    chunkSizeWarningLimit: 400,
    // Never inline fonts as data: URIs; the server CSP only allows font-src 'self'.
    assetsInlineLimit: (file) => (/\.(woff2?|ttf|otf)$/.test(file) ? false : undefined),
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {
              // The framework changes far less often than the application: its own
              // chunk stays in the browser cache across releases.
              name: 'framework',
              test: /node_modules[\\/](react|react-dom|scheduler|@tanstack[\\/](react-router|router-core|history|react-query|query-core))[\\/]/,
            },
            {
              // Design-system primitives and icons are shared by the shell and every
              // page: one chunk instead of dozens of sub-kilobyte requests.
              name: 'ui',
              test: /src[\\/]components[\\/]ui[\\/]|node_modules[\\/](@radix-ui|radix-ui|@floating-ui|lucide-react|react-remove-scroll[^\\/]*|aria-hidden|clsx|tailwind-merge|class-variance-authority)[\\/]/,
            },
          ],
        },
      },
    },
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
