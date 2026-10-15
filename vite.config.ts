import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'node:path';

export default defineConfig({
  root: 'apps/web',
  plugins: [react()],
  server: {
    proxy: { '/api/v1': 'http://127.0.0.1:8000' },
  },
  build: {
    outDir: '../../dist/web',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main: resolve(process.cwd(), 'apps/web/index.html'),
        admin: resolve(process.cwd(), 'apps/web/admin/index.html'),
      },
      output: {
        entryFileNames: (chunk) => chunk.name === 'admin' || chunk.facadeModuleId?.includes('/src/admin/')
          ? 'admin-assets/[name]-[hash].js'
          : 'assets/[name]-[hash].js',
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: (asset) => asset.name?.includes('admin')
          ? 'admin-assets/[name]-[hash][extname]'
          : 'assets/[name]-[hash][extname]',
      },
    },
  },
});
