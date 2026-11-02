import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // Server-only routing setting. API credentials never belong in frontend env.
  const env = loadEnv(mode, process.cwd(), 'KITESHIELD_');
  return {
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: env.KITESHIELD_API_PROXY_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  };
})
