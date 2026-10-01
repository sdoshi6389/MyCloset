import { execSync } from 'node:child_process'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

/* Which commit a running page was built from.
 *
 * Without this there is no way to tell a bug from a stale deploy: the same
 * screen looks identical either way, and the only evidence is whether the
 * fix is in the bundle. Vercel exposes the SHA at build time; locally we ask
 * git. The app prints it to the console on boot.
 */
function buildId() {
  const sha = process.env.VERCEL_GIT_COMMIT_SHA
    || (() => {
      try {
        return execSync('git rev-parse --short HEAD', { stdio: ['ignore', 'pipe', 'ignore'] })
          .toString().trim()
      } catch {
        return 'unknown'
      }
    })()
  return `${sha.slice(0, 7)} ${new Date().toISOString().slice(0, 16).replace('T', ' ')}Z`
}

// https://vite.dev/config/
export default defineConfig({
  define: { __BUILD_ID__: JSON.stringify(buildId()) },
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
