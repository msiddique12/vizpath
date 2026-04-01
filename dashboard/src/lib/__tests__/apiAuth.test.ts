import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getDetailedHealth, getTraces } from '../api'
import { setStoredApiKey } from '../apiKey'

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('dashboard API key header behavior', () => {
  let originalFetch: typeof fetch

  beforeEach(() => {
    originalFetch = globalThis.fetch
    setStoredApiKey('')
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
    setStoredApiKey('')
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
})
