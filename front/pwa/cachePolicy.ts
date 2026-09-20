// APP_ENV reaches the frontend as VITE_APP_ENV, including static dev builds.
export const pwaCacheEnabled = import.meta.env.PROD && import.meta.env.VITE_APP_ENV !== 'dev'
