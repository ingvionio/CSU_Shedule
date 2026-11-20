import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

import packageJson from './package.json'

export default defineConfig({
  // Версия сборки уходит в статистику (X-Client-Version, события ЛК продукта).
  define: { __APP_VERSION__: JSON.stringify(packageJson.version) },
  build: {
    rollupOptions: {
      input: {
        app: fileURLToPath(new URL('./index.html', import.meta.url)),
        download: fileURLToPath(new URL('./download/index.html', import.meta.url)),
        statistic: fileURLToPath(new URL('./statistic/index.html', import.meta.url)),
      },
    },
  },
  plugins: [
    react(),
    // PWA: манифест и свой service worker (src/sw.ts) — он показывает push-уведомления.
    VitePWA({
      strategies: 'injectManifest',
      srcDir: 'src',
      filename: 'sw.ts',
      registerType: 'autoUpdate',
      injectRegister: false,
      includeAssets: ['icons/*.png'],
      manifest: {
        name: 'Расписание ИИТ ЧелГУ',
        short_name: 'ИИТ',
        description: 'Расписание ИИТ, задания группы, личные заметки и сообщения',
        lang: 'ru',
        start_url: '/',
        display: 'standalone',
        background_color: '#f4f7fa',
        theme_color: '#152d42',
        icons: [
          { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/icons/icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      // В dev service worker тоже нужен — иначе push не проверить на localhost.
      devOptions: { enabled: true, type: 'module' },
    }),
  ],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
