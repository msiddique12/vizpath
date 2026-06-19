const DASHBOARD_API_KEY_STORAGE_KEY = 'vizpath_api_key'
const DASHBOARD_SESSION_API_KEY_STORAGE_KEY = 'vizpath_session_api_key'
let inMemoryApiKey = ''

function getEnvApiKey(): string {
  const configured = (import.meta.env.VITE_VIZPATH_API_KEY as string | undefined)?.trim()
  return configured || ''
}

export function getStoredApiKey(): string {
  if (typeof window === 'undefined') {
    return inMemoryApiKey
  }

  try {
    if (typeof window.sessionStorage?.getItem === 'function') {
      const sessionKey = window.sessionStorage.getItem(DASHBOARD_SESSION_API_KEY_STORAGE_KEY)?.trim()
      if (sessionKey) return sessionKey
    }
    if (typeof window.localStorage.getItem === 'function') {
      const legacyKey = window.localStorage.getItem(DASHBOARD_API_KEY_STORAGE_KEY)?.trim()
      if (legacyKey) {
        inMemoryApiKey = legacyKey
        window.sessionStorage?.setItem(DASHBOARD_SESSION_API_KEY_STORAGE_KEY, legacyKey)
        window.localStorage.removeItem(DASHBOARD_API_KEY_STORAGE_KEY)
        return legacyKey
      }
    }
    return inMemoryApiKey
  } catch {
    return inMemoryApiKey
  }
}

export function setStoredApiKey(apiKey: string): void {
  const normalized = apiKey.trim()
  inMemoryApiKey = normalized

  if (typeof window === 'undefined') {
    return
  }

  try {
    if (typeof window.localStorage?.removeItem === 'function') {
      window.localStorage.removeItem(DASHBOARD_API_KEY_STORAGE_KEY)
    }
    if (!normalized && typeof window.sessionStorage?.removeItem === 'function') {
      window.sessionStorage.removeItem(DASHBOARD_SESSION_API_KEY_STORAGE_KEY)
      return
    }
    if (typeof window.sessionStorage?.setItem === 'function') {
      window.sessionStorage.setItem(DASHBOARD_SESSION_API_KEY_STORAGE_KEY, normalized)
    }
  } catch {
    // Ignore browser storage failures (private mode/quota/security policies).
  }
}

export function getEffectiveApiKey(): string {
  return getStoredApiKey() || getEnvApiKey()
}

export { DASHBOARD_API_KEY_STORAGE_KEY, DASHBOARD_SESSION_API_KEY_STORAGE_KEY }
