import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import DemoPage from '../DemoPage'
import { MockWebSocket } from '../../test/mocks/websocket'
import { renderWithProviders } from '../../test/test-utils'

function createJsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('DemoPage websocket security UX', () => {
  let originalWebSocket: typeof WebSocket
  let originalFetch: typeof fetch

  beforeEach(() => {
    originalWebSocket = globalThis.WebSocket
    globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket
    MockWebSocket.reset()

    originalFetch = globalThis.fetch
    globalThis.fetch = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.endsWith('/health/detailed')) {
        return createJsonResponse({
          status: 'healthy',
          timestamp: new Date().toISOString(),
          version: 'test',
          checks: {
            database: { status: 'healthy' },
            redis: { status: 'healthy' },
            intelligence: { status: 'configured' },
          },
        })
      }

      if (url.includes('/demo/preflight')) {
        return createJsonResponse({
          ready: true,
          can_seed: true,
          checks: [],
          blockers: [],
          recommendations: [],
          fix_commands: [],
        })
      }

      if (url.includes('/intelligence/status')) {
        return createJsonResponse({
          nvidia_api_key_configured: true,
          model: 'test-model',
          base_url: 'https://api.nvcf.fake',
        })
      }

      if (url.includes('/demo/story-mode/latest')) {
        return createJsonResponse({
          found: false,
          scenario: null,
          seeded: 0,
          trace_ids: [],
          recommended_flow: {
            compare: '/compare?story-mode=fresh',
            trace_baseline: '/traces/tb',
            trace_candidate: '/traces/tc',
            trace_recovery: '/traces/tr',
            curation: '/curation',
          },
        })
      }

      throw new Error(`Unexpected fetch call: ${url}`)
    }) as unknown as typeof fetch
  })

  afterEach(() => {
    globalThis.WebSocket = originalWebSocket
    globalThis.fetch = originalFetch
  })

  it('surfaces auth failure message and blocks automatic retry', async () => {
    renderWithProviders(<DemoPage />, ['/demo'])

    await waitFor(() => expect(screen.getByText('Demo Mode')).toBeInTheDocument())
    expect(MockWebSocket.instances).toHaveLength(1)

    act(() => {
      MockWebSocket.latest().triggerClose(4001, 'Unauthorized: websocket key missing')
    })

    const banner = await screen.findByRole('status')
    expect(banner).toHaveTextContent('Live updates are unavailable')
    expect(screen.queryByRole('button', { name: 'Retry connection' })).not.toBeInTheDocument()
    expect(screen.getByText(/Use a websocket API key to reconnect/i)).toBeInTheDocument()
    expect(screen.getByLabelText('Websocket API key')).toBeInTheDocument()
    await waitFor(() => expect(MockWebSocket.instances).toHaveLength(1))
  })

  it('allows reconnect with a runtime websocket API key', async () => {
    renderWithProviders(<DemoPage />, ['/demo'])

    await waitFor(() => expect(screen.getByText('Demo Mode')).toBeInTheDocument())
    expect(MockWebSocket.instances).toHaveLength(1)

    act(() => {
      MockWebSocket.latest().triggerClose(4001, 'Unauthorized: websocket key missing')
    })

    const input = await screen.findByLabelText('Websocket API key')
    const submitButton = screen.getByRole('button', { name: 'Connect with API key' })

    await act(async () => {
      await fireEvent.change(input, { target: { value: 'runtime-demo-key' } })
      await fireEvent.click(submitButton)
    })

    await waitFor(() => {
      expect(MockWebSocket.instances).toHaveLength(2)
      expect(MockWebSocket.latest().url).toContain('api_key=runtime-demo-key')
    })
  })

  it('allows manual retry after retryable websocket disconnects', async () => {
    renderWithProviders(<DemoPage />, ['/demo'])

    await waitFor(() => expect(screen.getByText('Demo Mode')).toBeInTheDocument())
    expect(MockWebSocket.instances).toHaveLength(1)

    act(() => {
      MockWebSocket.latest().triggerClose(1000, 'Normal close')
    })

    await waitFor(() => {
      expect(
        screen.getByText('Live updates disconnected. Retrying automatically when possible.')
      ).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Retry connection' })).toBeInTheDocument()
    })

    act(() => {
      fireEvent.click(screen.getByRole('button', { name: 'Retry connection' }))
    })

    await waitFor(() => {
      expect(MockWebSocket.instances).toHaveLength(2)
    })
  })
})
