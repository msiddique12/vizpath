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

  const resetTracePageStorage = () => {
    const storage = window.localStorage as Storage & {
      removeItem?: (key: string) => void
    }
    storage.removeItem?.('traces_filters_v1')
    storage.removeItem?.('traces_filter_presets_v1')
    storage.removeItem?.('traces_pinned_v1')
    storage.removeItem?.('vizpath_api_key')
  }

  beforeEach(() => {
    resetTracePageStorage()

    originalWebSocket = globalThis.WebSocket
    globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket
    MockWebSocket.reset()

    originalFetch = globalThis.fetch
    globalThis.fetch = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = resolveUrl(input)
      const requestMethod = init?.method ?? (input instanceof Request ? input.method : 'GET')

      if (url.includes('/curation/traces')) {
        return createJsonResponse([])
      }

      if (url.includes('/curation/labels/') && requestMethod === 'GET') {
        return new Response(JSON.stringify({ detail: 'Label not found' }), {
          status: 404,
          headers: { 'Content-Type': 'application/json' },
        })
      }

      if (url.includes('/curation/labels') && requestMethod === 'POST') {
        const body = typeof init?.body === 'string' ? JSON.parse(init.body) : {}
        return createJsonResponse({
          trace_id: body.trace_id ?? 'trace-incident-1',
          label: body.label ?? null,
          quality_score: null,
          notes: null,
          exported: false,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        })
      }

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

      if (url.includes('/projects/me/budget/status')) {
        return createJsonResponse({
          month_start: new Date().toISOString(),
          month_end: new Date().toISOString(),
          tokens_used: 90,
          cost_used: 0.9,
          monthly_token_limit: 100,
          monthly_cost_limit: 1.0,
          token_usage_percent: 90,
          cost_usage_percent: 90,
          alert_threshold_percent: 80,
          token_alert_triggered: true,
          cost_alert_triggered: true,
          alert_triggered: true,
          hard_stop_enabled: true,
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
    resetTracePageStorage()
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

  it('shows budget guardrail status card when budget data is available', async () => {
    _renderWithProviders(<TracesPage />, ['/traces'])

    await waitFor(() => expect(screen.getByText('Demo trace')).toBeInTheDocument())
    expect(screen.getByText('Budget Guardrails')).toBeInTheDocument()
    expect(screen.getByText('Hard stop on')).toBeInTheDocument()
    expect(screen.getByText('Token budget')).toBeInTheDocument()
    expect(screen.getByText('Cost budget')).toBeInTheDocument()
  })

  it('renders incident feed entries from intelligence incidents endpoint', async () => {
    globalThis.fetch = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = resolveUrl(input)
      const requestMethod = init?.method ?? (input instanceof Request ? input.method : 'GET')

      if (url.includes('/curation/traces')) {
        return createJsonResponse([])
      }

      if (url.includes('/curation/labels/') && requestMethod === 'GET') {
        return new Response(JSON.stringify({ detail: 'Label not found' }), {
          status: 404,
          headers: { 'Content-Type': 'application/json' },
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

      if (url.includes('/projects/me/budget/status')) {
        return createJsonResponse({
          month_start: new Date().toISOString(),
          month_end: new Date().toISOString(),
          tokens_used: 90,
          cost_used: 0.9,
          monthly_token_limit: 100,
          monthly_cost_limit: 1.0,
          token_usage_percent: 90,
          cost_usage_percent: 90,
          alert_threshold_percent: 80,
          token_alert_triggered: true,
          cost_alert_triggered: true,
          alert_triggered: true,
          hard_stop_enabled: true,
        })
      }

      if (url.includes('/intelligence/incidents')) {
        return createJsonResponse({
          incidents: [
            {
              trace_id: 'trace-incident-1',
              trace_name: 'Tool timeout regression',
              trace_status: 'error',
              created_at: new Date().toISOString(),
              baseline_trace_id: 'trace-baseline-1',
              risk_score: 84,
              risk_level: 'high',
              signal_count: 2,
              top_signal: 'Reliability regression',
              top_actions: ['Fix newly introduced erroring spans before other optimizations.'],
              curation: null,
            },
          ],
          total: 1,
          limit: 5,
          offset: 0,
          generated_at: new Date().toISOString(),
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

    _renderWithProviders(<TracesPage />, ['/traces'])

    await waitFor(() => expect(screen.getByText('Tool timeout regression')).toBeInTheDocument())
    expect(screen.getByText('Incident Feed')).toBeInTheDocument()
    expect(screen.getByText('Reliability regression')).toBeInTheDocument()
    expect(screen.getByText('risk 84')).toBeInTheDocument()

    const compareLink = screen.getByRole('link', { name: 'Compare' })
    expect(compareLink.getAttribute('href')).toBe('/compare?traceA=trace-baseline-1&traceB=trace-incident-1')

    fireEvent.click(screen.getByRole('button', { name: 'Mark failure' }))
    await waitFor(() => {
      const calls = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls
      const labelCall = calls.find(([input, init]) => {
        const url = resolveUrl(input as RequestInfo | URL)
        return url.includes('/curation/labels') && (init as RequestInit | undefined)?.method === 'POST'
      })
      expect(labelCall).toBeDefined()
      const body = JSON.parse(String((labelCall?.[1] as RequestInit | undefined)?.body ?? '{}'))
      expect(body.trace_id).toBe('trace-incident-1')
      expect(body.label).toBe('failure')
    })
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

  it('supports bulk labels and compare from selected traces', async () => {
    globalThis.fetch = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = resolveUrl(input)
      const method = init?.method ?? (input instanceof Request ? input.method : 'GET')

      if (url.includes('/curation/labels') && method === 'POST') {
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
          trace_count: 2,
          success_rate: 100,
          running_count: 0,
          error_count: 0,
          p50_duration_ms: 42,
          p95_duration_ms: 120,
          avg_tokens: 22,
          avg_cost: 0.0009,
        })
      }

      if (url.includes('/projects/me/budget/status')) {
        return createJsonResponse({
          month_start: new Date().toISOString(),
          month_end: new Date().toISOString(),
          tokens_used: 0,
          cost_used: 0,
          monthly_token_limit: null,
          monthly_cost_limit: null,
          token_usage_percent: null,
          cost_usage_percent: null,
          alert_threshold_percent: 80,
          token_alert_triggered: false,
          cost_alert_triggered: false,
          alert_triggered: false,
          hard_stop_enabled: false,
        })
      }

      return createJsonResponse({
        traces: [
          {
            id: 'trace-1',
            name: 'Demo trace A',
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
          {
            id: 'trace-2',
            name: 'Demo trace B',
            status: 'success',
            start_time: new Date().toISOString(),
            end_time: new Date().toISOString(),
            duration_ms: 55,
            metadata: {},
            total_tokens: 30,
            total_cost: 0.002,
            span_count: 8,
            error_count: 0,
            created_at: new Date().toISOString(),
          },
        ],
        total: 2,
        limit: 50,
        offset: 0,
      })
    }) as unknown as typeof fetch

    _renderWithProviders(<TracesPage />, ['/traces'])

    await waitFor(() => expect(screen.getByText('Demo trace A')).toBeInTheDocument())
    expect(screen.getByText('Demo trace B')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Select trace trace-1' }))
    fireEvent.click(screen.getByRole('button', { name: 'Select trace trace-2' }))

    const compareLink = await screen.findByRole('link', { name: 'Compare selected' })
    expect(compareLink.getAttribute('href')).toBe('/compare?traceA=trace-1&traceB=trace-2')

    fireEvent.click(screen.getByRole('button', { name: 'Label selected: Good' }))

    await waitFor(() => {
      const calls = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls
      const labelCalls = calls.filter(([input, init]) => {
        const url = resolveUrl(input as RequestInfo | URL)
        return url.includes('/curation/labels') && (init as RequestInit | undefined)?.method === 'POST'
      })
      expect(labelCalls).toHaveLength(2)
    })
  })

  it('supports pinning traces and pinned-only view', async () => {
    globalThis.fetch = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = resolveUrl(input)
      if (url.includes('/traces/summary')) {
        return createJsonResponse({
          window_days: 7,
          trace_count: 2,
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
            name: 'Pinned candidate',
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
          {
            id: 'trace-2',
            name: 'Unpinned trace',
            status: 'success',
            start_time: new Date().toISOString(),
            end_time: new Date().toISOString(),
            duration_ms: 55,
            metadata: {},
            total_tokens: 30,
            total_cost: 0.002,
            span_count: 8,
            error_count: 0,
            created_at: new Date().toISOString(),
          },
        ],
        total: 2,
        limit: 50,
        offset: 0,
      })
    }) as unknown as typeof fetch

    _renderWithProviders(<TracesPage />, ['/traces'])

    await waitFor(() => expect(screen.getByText('Pinned candidate')).toBeInTheDocument())
    expect(screen.getByText('Unpinned trace')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Pin trace trace-1' }))
    fireEvent.click(screen.getByRole('button', { name: 'Pinned only' }))

    await waitFor(() => {
      expect(screen.getByText('Pinned candidate')).toBeInTheDocument()
      expect(screen.queryByText('Unpinned trace')).not.toBeInTheDocument()
    })
  })

  it('shows risk flags for traces with loop and resource pressure signals', async () => {
    globalThis.fetch = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = resolveUrl(input)
      if (url.includes('/traces/summary')) {
        return createJsonResponse({
          window_days: 7,
          trace_count: 1,
          success_rate: 0,
          running_count: 0,
          error_count: 1,
          p50_duration_ms: 60000,
          p95_duration_ms: 60000,
          avg_tokens: 18000,
          avg_cost: 0.5,
        })
      }

      return createJsonResponse({
        traces: [
          {
            id: 'trace-risky',
            name: 'Retry loop agent',
            status: 'error',
            start_time: new Date().toISOString(),
            end_time: new Date().toISOString(),
            duration_ms: 60000,
            metadata: { reason: 'retrying in loop due to tool timeout' },
            total_tokens: 18000,
            total_cost: 0.4,
            span_count: 48,
            error_count: 3,
            created_at: new Date().toISOString(),
          },
        ],
        total: 1,
        limit: 50,
        offset: 0,
      })
    }) as unknown as typeof fetch

    _renderWithProviders(<TracesPage />, ['/traces'])

    await waitFor(() => expect(screen.getByText('Retry loop agent')).toBeInTheDocument())
    expect(screen.getByText('Loop risk')).toBeInTheDocument()
    expect(screen.getByText('Long runtime')).toBeInTheDocument()
    expect(screen.getByText('Token pressure')).toBeInTheDocument()
  })

  it('saves inline notes from trace rows', async () => {
    _renderWithProviders(<TracesPage />, ['/traces'])

    await waitFor(() => expect(screen.getByText('Demo trace')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Edit note for trace-1' }))
    const noteInput = await screen.findByPlaceholderText('Add handoff note')
    fireEvent.change(noteInput, { target: { value: 'Investigate retry timeout path' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => {
      const calls = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls
      const noteCall = calls.find(([input, init]) => {
        const url = resolveUrl(input as RequestInfo | URL)
        if (!url.includes('/curation/labels') || (init as RequestInit | undefined)?.method !== 'POST') {
          return false
        }
        const body = typeof (init as RequestInit | undefined)?.body === 'string'
          ? JSON.parse((init as RequestInit).body as string)
          : {}
        return body.notes === 'Investigate retry timeout path'
      })
      expect(noteCall).toBeDefined()
    })
  })

  it('shows quick-start commands in empty state when no traces exist', async () => {
    globalThis.fetch = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = resolveUrl(input)
      if (url.includes('/traces/summary')) {
        return createJsonResponse({
          window_days: 7,
          trace_count: 0,
          success_rate: 0,
          running_count: 0,
          error_count: 0,
          p50_duration_ms: 0,
          p95_duration_ms: 0,
          avg_tokens: 0,
          avg_cost: 0,
        })
      }

      return createJsonResponse({
        traces: [],
        total: 0,
        limit: 50,
        offset: 0,
      })
    }) as unknown as typeof fetch

    _renderWithProviders(<TracesPage />, ['/traces'])

    expect(await screen.findByText('No traces yet. Start your first run:')).toBeInTheDocument()
    expect(screen.getByText('./demo.sh')).toBeInTheDocument()
    expect(
      screen.getByText('python -m examples.code_agent.run "How does the intelligence module work?"')
    ).toBeInTheDocument()
  })
})
