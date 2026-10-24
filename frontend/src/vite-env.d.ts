/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Origin of the ICEFLOW API, e.g. https://ICEFLOW-api.onrender.com
   *
   * Leave unset for local development and for single-container deployments, where the API is
   * same-origin. Set it only when the frontend bundle is hosted separately from the API.
   */
  readonly VITE_API_BASE_URL?: string;
  /** Public Mapbox token used by the regional context map. */
  readonly VITE_MAPBOX_ACCESS_TOKEN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
