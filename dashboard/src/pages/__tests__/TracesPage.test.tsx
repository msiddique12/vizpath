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

function resolveUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') {
    return input
  }
  if (input instanceof URL) {
    return input.toString()
  }
  return input.url
}

describe('TracesPage websocket security UX', () => {
  let originalWebSocket: typeof WebSocket
  let originalFetch: typeof fetch

  beforeEach(() => {
    originalWebSocket = globalThis.WebSocket
    globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket
    MockWebSocket.reset()

    originalFetch = globalThis.fetch
    globalThis.fetch = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = resolveUrl(input)
      const requestMethod = init?.method ?? (input instanceof Request ? input.method : 'GET')

      if (url.includes('/curation/labels') && requestMethod === 'POST') {
        const body = typeof init?.body === 'string' ? JSON.parse(init.body) : {}
        return createJsonResponse({
          trace_id: body.trace_id ?? 'trace-1',
          label: body.label ?? null,
          quality_score: null,
          notes: null,
          exported: false,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        })
      }

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

  it('surfaces auth failure message and blocks manual websocket reconnect', async () => {
    const renderResult = _renderWithProviders(<TracesPage />, ['/traces'])

    await waitFor(() => expect(screen.getByText('Demo trace')).toBeInTheDocument())
    expect(MockWebSocket.instances).toHaveLength(1)

    act(() => {
      MockWebSocket.latest().triggerClose(4001, 'Unauthorized: Invalid or missing API key')
    })

    const banner = await screen.findByRole('status')
    expect(banner).toHaveTextContent('Live updates are unavailable')
    expect(screen.queryByRole('button', { name: 'Retry connection' })).not.toBeInTheDocument()
    expect(screen.getByText(/Use a websocket API key to reconnect/)).toBeInTheDocument()
    expect(screen.getByLabelText('Websocket API key')).toBeInTheDocument()

    await waitFor(() => {
      expect(MockWebSocket.instances).toHaveLength(1)
    })

    renderResult.unmount()
  })

  it('allows users to reconnect with a runtime websocket API key', async () => {
    const renderResult = _renderWithProviders(<TracesPage />, ['/traces'])

    await waitFor(() => expect(screen.getByText('Demo trace')).toBeInTheDocument())
    expect(MockWebSocket.instances).toHaveLength(1)

    act(() => {
      MockWebSocket.latest().triggerClose(4001, 'Unauthorized: Invalid or missing API key')
    })

    const input = await screen.findByLabelText('Websocket API key')
    const submitButton = screen.getByRole('button', { name: 'Connect with API key' })

    await act(async () => {
      await fireEvent.change(input, { target: { value: 'manual-runtime-key' } })
      await fireEvent.click(submitButton)
    })

    await waitFor(() => {
      expect(MockWebSocket.instances).toHaveLength(2)
      expect(MockWebSocket.latest().url).toContain('api_key=manual-runtime-key')
    })

    renderResult.unmount()
  })

  it('allows manual retry for retryable websocket disconnects', async () => {
    _renderWithProviders(<TracesPage />, ['/traces'])

    await waitFor(() => expect(screen.getByText('Demo trace')).toBeInTheDocument())
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

  it('saves and reapplies named filter presets', async () => {
    _renderWithProviders(<TracesPage />, ['/traces'])

    await waitFor(() => expect(screen.getByText('Demo trace')).toBeInTheDocument())

    const getSearchInput = () => screen.getByPlaceholderText('Search trace name')

    fireEvent.change(getSearchInput(), { target: { value: 'demo' } })

    const savedFilterNameInput = await screen.findByLabelText('Saved filter name')
    fireEvent.change(savedFilterNameInput, { target: { value: 'Errors view' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save current filter' }))

    expect(await screen.findByRole('button', { name: 'Errors view' })).toBeInTheDocument()

    fireEvent.change(getSearchInput(), { target: { value: '' } })
    expect(getSearchInput()).toHaveValue('')

    fireEvent.click(screen.getByRole('button', { name: 'Errors view' }))
    await waitFor(() => {
      expect(getSearchInput()).toHaveValue('demo')
    })
  })

  it('sends quick label actions from trace rows', async () => {
    _renderWithProviders(<TracesPage />, ['/traces'])

    await waitFor(() => expect(screen.getByText('Demo trace')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Good' }))

    await waitFor(() => {
      const calls = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls
      const labelCall = calls.find(([input, init]) => {
        const url = resolveUrl(input as RequestInfo | URL)
        return url.includes('/curation/labels') && (init as RequestInit | undefined)?.method === 'POST'
      })

      expect(labelCall).toBeDefined()
      const requestInit = labelCall?.[1] as RequestInit | undefined
      expect(requestInit?.body).toBe(JSON.stringify({ trace_id: 'trace-1', label: 'good' }))
    })
  })
})
