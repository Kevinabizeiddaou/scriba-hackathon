/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Scriba API root. Unset on localhost:5173 means http://localhost:8000. */
  readonly VITE_API_BASE_URL?: string
}
