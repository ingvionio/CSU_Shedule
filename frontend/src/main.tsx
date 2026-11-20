import React, { Suspense, lazy } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { registerSW } from 'virtual:pwa-register'

import { App } from './App'
import { AndroidDownload } from './pages/AndroidDownload'
import './styles.css'

// Service worker: офлайн-статика и push-уведомления. Новая версия ставится сама.
registerSW({ immediate: true })

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

const isDownloadPage = /^\/download(?:\/index\.html|\/)?$/.test(window.location.pathname)
// ЛК продукта: открывается только по прямому адресу, ссылок из приложения нет.
// Отдельный чанк: студентам код ЛК и графиков не нужен.
const ProductStatistics = lazy(() => import('./pages/product/ProductStatistics').then((module) => ({ default: module.ProductStatistics })))
const isStatisticPage = /^\/statistic(?:\/index\.html|\/)?$/.test(window.location.pathname)

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      {isStatisticPage ? <Suspense fallback={null}><ProductStatistics /></Suspense> : isDownloadPage ? <AndroidDownload /> : <App />}
    </QueryClientProvider>
  </React.StrictMode>,
)
