import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { analyzeTrace, ApiError, getDetailedHealth, getTraces } from '../api'
import {
  DASHBOARD_API_KEY_STORAGE_KEY,
  DASHBOARD_SESSION_API_KEY_STORAGE_KEY,
  getStoredApiKey,
  setStoredApiKey,
} from '../apiKey'

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function createMemoryStorage(): Storage {
  const values = new Map<string, string>()
  return {
    get length() {
      return values.size
    },
    clear: () => values.clear(),
    getItem: (key: string) => values.get(key) ?? null,
    key: (index: number) => Array.from(values.keys())[index] ?? null,
    removeItem: (key: string) => values.delete(key),
    setItem: (key: string, value: string) => values.set(key, value),
  }
}

describe('dashboard API key header behavior', () => {
  let originalFetch: typeof fetch

  beforeEach(() => {
    originalFetch = globalThis.fetch
    Object.defineProperty(window, 'localStorage', {
      value: createMemoryStorage(),
      configurable: true,
    })
    Object.defineProperty(window, 'sessionStorage', {
      value: createMemoryStorage(),
      configurable: true,
    })
    setStoredApiKey('')
    window.localStorage.removeItem(DASHBOARD_API_KEY_STORAGE_KEY)
    window.sessionStorage.removeItem(DASHBOARD_SESSION_API_KEY_STORAGE_KEY)
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
    setStoredApiKey('')
    window.localStorage.removeItem(DASHBOARD_API_KEY_STORAGE_KEY)
    window.sessionStorage.removeItem(DASHBOARD_SESSION_API_KEY_STORAGE_KEY)
  })

  it('sends X-API-Key on API base requests when a runtime key is stored', async () => {
    setStoredApiKey('stored-test-key')
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        traces: [],
        total: 0,
        limit: 1,
        offset: 0,
      })
    )
    globalThis.fetch = fetchMock as unknown as typeof fetch

    await getTraces(1, 0)

    const init = fetchMock.mock.calls[0][1] as RequestInit | undefined
    const headers = new Headers(init?.headers)
    expect(headers.get('X-API-Key')).toBe('stored-test-key')
  })

  it('stores runtime keys in session storage instead of local storage', () => {
    setStoredApiKey('session-test-key')

    expect(window.sessionStorage.getItem(DASHBOARD_SESSION_API_KEY_STORAGE_KEY)).toBe('session-test-key')
    expect(window.localStorage.getItem(DASHBOARD_API_KEY_STORAGE_KEY)).toBeNull()
  })

  it('migrates legacy local storage keys into session storage', () => {
    window.localStorage.setItem(DASHBOARD_API_KEY_STORAGE_KEY, 'legacy-test-key')

    expect(getStoredApiKey()).toBe('legacy-test-key')
    expect(window.sessionStorage.getItem(DASHBOARD_SESSION_API_KEY_STORAGE_KEY)).toBe('legacy-test-key')
    expect(window.localStorage.getItem(DASHBOARD_API_KEY_STORAGE_KEY)).toBeNull()
  })

  it('sends X-API-Key on root API requests when a runtime key is stored', async () => {
    setStoredApiKey('stored-test-key')
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        status: 'healthy',
        timestamp: new Date().toISOString(),
        version: 'test',
        checks: {
          database: { status: 'healthy' },
          redis: { status: 'healthy' },
          intelligence: { status: 'configured' },
        },
      })
    )
    globalThis.fetch = fetchMock as unknown as typeof fetch

    await getDetailedHealth()

    const init = fetchMock.mock.calls[0][1] as RequestInit | undefined
    const headers = new Headers(init?.headers)
    expect(headers.get('X-API-Key')).toBe('stored-test-key')
  })

  it('throws detailed ApiError for budget guardrail 429 responses', async () => {
    globalThis.fetch = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            detail: {
              code: 'intelligence_daily_budget_exceeded',
              message: 'Daily intelligence call budget exhausted for this project.',
            },
          }),
          {
            status: 429,
            headers: {
              'Content-Type': 'application/json',
              'Retry-After': '120',
            },
          }
        )
      )
    ) as unknown as typeof fetch

    let thrown: unknown
    try {
      await analyzeTrace('trace-budget')
    } catch (error) {
      thrown = error
    }

    expect(thrown).toBeInstanceOf(ApiError)
    expect(thrown).toMatchObject({
      status: 429,
      code: 'intelligence_daily_budget_exceeded',
      retryAfterSeconds: 120,
    })
    expect((thrown as Error).message).toContain('Daily intelligence call budget exhausted for this project.')
  })
})
