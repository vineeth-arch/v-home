import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Phone companion: index.html at root, deployed to Vercel from dist/.
export default defineConfig({ plugins: [react()], build: { outDir: 'dist' }, test: { environment: 'jsdom', exclude: ['**/node_modules/**', '**/dist/**', '.claude/**', 'android/**', 'companion/**'] } })
