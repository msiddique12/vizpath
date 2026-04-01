const DASHBOARD_API_KEY_STORAGE_KEY = 'vizpath_api_key'
let inMemoryApiKey = ''

function getEnvApiKey(): string {
  const configured = (import.meta.env.VITE_VIZPATH_API_KEY as string | undefined)?.trim()
  return configured || ''
}

export function getStoredApiKey(): string {
  if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') {
    return inMemoryApiKey
  }

  try {
    if (typeof window.localStorage.getItem === 'function') {
      return window.localStorage.getItem(DASHBOARD_API_KEY_STORAGE_KEY)?.trim() || inMemoryApiKey
    }
    return inMemoryApiKey
  } catch {
    return inMemoryApiKey
  }
}

export function setStoredApiKey(apiKey: string): void {
  const normalized = apiKey.trim()
  inMemoryApiKey = normalized

  if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') {
    return
  }

  try {
    if (!normalized && typeof window.localStorage.removeItem === 'function') {
      window.localStorage.removeItem(DASHBOARD_API_KEY_STORAGE_KEY)
      return
    }
    if (typeof window.localStorage.setItem === 'function') {
      window.localStorage.setItem(DASHBOARD_API_KEY_STORAGE_KEY, normalized)
    }
  } catch {
    // Ignore localStorage write failures (private mode/quota/security policies).
  }
}

export function getEffectiveApiKey(): string {
  return getStoredApiKey() || getEnvApiKey()
}

export { DASHBOARD_API_KEY_STORAGE_KEY }
