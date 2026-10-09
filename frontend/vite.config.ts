import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import fs from 'fs';
import path from 'path';
import {defineConfig, Plugin} from 'vite';

function getVersionFilePath(): string | null {
  const parentPath = path.resolve(__dirname, '../version.json');
  if (fs.existsSync(parentPath)) return parentPath;

  return null;
}

function rootVersionPlugin(): Plugin {
  return {
    name: 'serve-root-version-json',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url === '/version.json') {
          try {
            const filePath = getVersionFilePath();
            if (filePath) {
              const content = fs.readFileSync(filePath, 'utf-8');
              res.setHeader('Content-Type', 'application/json');
              res.end(content);
              return;
            }
          } catch {}
        }
        next();
      });
    },
  };
}

export default defineConfig(() => {
  return {
    plugins: [react(), tailwindcss(), rootVersionPlugin()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, '.'),
      },
    },
    server: {
      // HMR is disabled in AI Studio via DISABLE_HMR env var.
      // Do not modify—file watching is disabled to prevent flickering during agent edits.
      hmr: process.env.DISABLE_HMR !== 'true',
      // Disable file watching when DISABLE_HMR is true to save CPU during agent edits.
      watch: process.env.DISABLE_HMR === 'true' ? null : {},
      proxy: process.env.BACKEND_URL ? {
        '/api': {
          target: process.env.BACKEND_URL,
          changeOrigin: true,
        },
      } : undefined,
    },
    build: {
      outDir: process.env.BUILD_OUT_DIR || (fs.existsSync(path.resolve(__dirname, '../backend')) ? path.resolve(__dirname, '../static') : 'dist'),
      emptyOutDir: true,
    },
  };
});
