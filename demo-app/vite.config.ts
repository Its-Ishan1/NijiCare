import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    // If another app is already on 5173, Vite will use the next available port.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8081',
        changeOrigin: false,
      },
    },
  },
  preview: {
    host: '127.0.0.1',
    port: 5173,
  },
});
