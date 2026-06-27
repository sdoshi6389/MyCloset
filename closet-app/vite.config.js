import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/icons':     'http://localhost:5000',
      '/uploads':   'http://localhost:5000',
      '/dressed':   'http://localhost:5000',
      '/processed': 'http://localhost:5000',
      '/static':    'http://localhost:5000',
      '/feed/images': 'http://localhost:5000',
    }
  }
})
