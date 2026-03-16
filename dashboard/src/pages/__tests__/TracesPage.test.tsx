import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { renderWithProviders as _renderWithProviders } from '../../test/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import TracesPage from '../TracesPage'
import { MockWebSocket } from '../../test/mocks/websocket'

function createJsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('TracesPage websocket security UX', () => {
  let originalWebSocket: typeof WebSocket
  let originalFetch: typeof fetch

  beforeEach(() => {
    originalWebSocket = globalThis.WebSocket
    globalThis.WebSocket = MockWebSocket as typeof WebSocket
    MockWebSocket.reset()

    originalFetch = globalThis.fetch
    globalThis.fetch = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/traces/summary')) {
        return createJsonResponse({
          window_days: 7,
          trace_count: 1,
          success_rate: 100,
          running_count: 0,
          error_count: 0,
          p50_duration_ms: 42,
          p95_duration_ms: 120,
          avg_tokens: 22,
          avg_cost: 0.0009,
        })
      }

      return createJsonResponse({
        traces: [
          {
            id: 'trace-1',
            name: 'Demo trace',
            status: 'success',
            start_time: new Date().toISOString(),
            end_time: new Date().toISOString(),
            duration_ms: 45,
            metadata: {},
            total_tokens: 20,
            total_cost: 0.001,
            span_count: 5,
            error_count: 0,
            created_at: new Date().toISOString(),
          },
        ],
        total: 1,
        limit: 50,
        offset: 0,
      })
    }) as unknown as typeof fetch
  })

  afterEach(() => {
    globalThis.WebSocket = originalWebSocket
    globalThis.fetch = originalFetch
  })

  it('surfaces auth failure message and offers retry action', async () => {
    const renderResult = _renderWithProviders(<TracesPage />, ['/traces'])

    await waitFor(() => expect(screen.getByText('Demo trace')).toBeInTheDocument())
    expect(MockWebSocket.instances).toHaveLength(1)

    act(() => {
      MockWebSocket.latest().triggerClose(4001, 'Unauthorized: Invalid or missing API key')
    })

    const banner = await screen.findByRole('status')
    expect(banner).toHaveTextContent('Live updates are unavailable')
    expect(screen.getByRole('button', { name: 'Retry connection' })).toBeInTheDocument()

    act(() => {
      fireEvent.click(screen.getByRole('button', { name: 'Retry connection' }))
    })
    await waitFor(() => {
      expect(MockWebSocket.instances).toHaveLength(2)
    })

    renderResult.unmount()
  })
})
