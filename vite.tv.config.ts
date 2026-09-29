import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import { cpSync, renameSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'

// Chromium blocks type="module" scripts on file:// (the IPK origin), so the TV build is one IIFE
// and the html tag is rewritten to a plain deferred-at-end-of-body script.
const tvHtml = (): Plugin => ({
  name: 'tv-html',
  apply: 'build',
  enforce: 'post',
  transformIndexHtml(html) {
    const m = html.match(/<script[^>]*src="([^"]+)"[^>]*><\/script>/)
    if (!m) return html
    return html.replace(m[0], '').replace('</body>', `<script src="${m[1]}"></script></body>`)
  },
  closeBundle() {
    const out = resolve('dist-tv')
    if (existsSync(`${out}/tv.html`)) renameSync(`${out}/tv.html`, `${out}/index.html`)
    cpSync(resolve('webos'), out, { recursive: true })
  },
})

export default defineConfig({
  base: './',
  plugins: [react(), tvHtml()],
  publicDir: 'public',
  build: {
    outDir: 'dist-tv',
    target: 'chrome108',
    modulePreload: false,
    rollupOptions: { input: resolve('tv.html'), output: { format: 'iife' } },
  },
})
