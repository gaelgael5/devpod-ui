import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';
export default defineConfig({
    plugins: [react()],
    resolve: {
        alias: { '@': path.resolve(__dirname, './src') },
    },
    server: {
        proxy: {
            '/auth': { target: 'http://localhost:8080', changeOrigin: true },
            '/me': { target: 'http://localhost:8080', changeOrigin: true },
            '/admin': { target: 'http://localhost:8080', changeOrigin: true },
            '/recipes': { target: 'http://localhost:8080', changeOrigin: true },
            '/health': { target: 'http://localhost:8080', changeOrigin: true },
        },
    },
});
