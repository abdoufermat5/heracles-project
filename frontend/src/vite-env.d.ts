/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_MOCK?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

/** Build id of the SPA (`HERACLES_BUILD_ID` or the package version), set by vite.config. */
declare const __APP_VERSION__: string
