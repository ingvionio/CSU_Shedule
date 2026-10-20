/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Адрес бэкенда, например http://localhost:8000 */
  readonly VITE_API_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
