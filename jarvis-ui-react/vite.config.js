import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

/**
 * Map the browser-facing /api contract onto the routes the FastAPI core really serves.
 *
 * The dashboard always talks to /api/... so that one relative base works in dev and in the
 * nginx container. Core exposes /chat and /jobs/{id} WITHOUT the /api prefix, and only
 * /api/global-tenders has the prefixed alias, so those paths are rewritten here.
 * nginx.conf in the production image performs the identical mapping (see README).
 */
export function rewriteApiPath(path) {
  if (path === '/api/chat') return '/chat';
  if (path.startsWith('/api/jobs/')) return path.replace('/api/jobs/', '/jobs/');

  const pitch = path.match(/^\/api\/global-tenders\/([^/]+)\/pitch(\?.*)?$/);
  if (pitch) return `/global-tenders/${pitch[1]}/pitch${pitch[2] || ''}`;

  // /api/global-tenders, /api/approvals, /api/host/*, /api/voice/* pass through unchanged.
  return path;
}

export default defineConfig(({ mode }) => {
  // Load every variable, including secrets without the VITE_ prefix, in this Node.js config
  // process only. JARVIS_API_TOKEN is never exposed through `define` or an import.meta.env key.
  const env = loadEnv(mode, process.cwd(), '');
  const backend = env.JARVIS_BACKEND_URL || 'http://localhost:8080';
  const token = (env.JARVIS_API_TOKEN || '').trim();

  const proxy = {
    '/api': {
      target: backend,
      changeOrigin: true,
      secure: false,
      rewrite: rewriteApiPath,
      configure: (proxyServer) => {
        proxyServer.on('proxyReq', (proxyReq) => {
          if (token) {
            proxyReq.setHeader('Authorization', `Bearer ${token}`);
          }
        });
      },
    },
  };

  return {
    plugins: [react()],
    server: {
      port: 5173,
      strictPort: false,
      host: '127.0.0.1',
      proxy,
    },
    preview: {
      port: 4173,
      proxy,
    },
    build: {
      outDir: 'dist',
      sourcemap: false,
    },
  };
});
