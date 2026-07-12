import { execSync } from 'child_process';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';
// Sha court du commit courant, injecté comme app.version pour Faro (télémétrie
// navigateur) — permet de relier une erreur/un log vus dans Grafana au build
// exact qui l'a produit. 'unknown' si .git est absent (build hors dépôt).
function gitShortSha() {
    try {
        return execSync('git rev-parse --short HEAD').toString().trim();
    }
    catch {
        return 'unknown';
    }
}
export default defineConfig({
    plugins: [react()],
    define: {
        __APP_VERSION__: JSON.stringify(gitShortSha()),
    },
    resolve: {
        alias: { '@': path.resolve(__dirname, './src') },
    },
    server: {
        proxy: {
            '/auth': { target: 'http://localhost:8080', changeOrigin: true },
            '/me': { target: 'http://localhost:8080', changeOrigin: true },
            '/admin': { target: 'http://localhost:8080', changeOrigin: true },
            '/recipes': { target: 'http://localhost:8080', changeOrigin: true },
            '/plugins': { target: 'http://localhost:8080', changeOrigin: true },
            '/profiles': { target: 'http://localhost:8080', changeOrigin: true },
            '/health': { target: 'http://localhost:8080', changeOrigin: true },
        },
    },
});
