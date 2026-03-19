import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { renderWithProviders } from '../../test/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ComparisonPage from '../ComparisonPage'

function createJsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const traces = [
  {
    id: 'trace-a',
    name: 'Trace Alpha',
    status: 'success',
    start_time: new Date().toISOString(),
    end_time: new Date().toISOString(),
    duration_ms: 120,
    metadata: {},
    total_tokens: 11,
    total_cost: 0.005,
    span_count: 3,
    error_count: 0,
    created_at: new Date().toISOString(),
  },
  {
    id: 'trace-b',
    name: 'Trace Beta',
    status: 'success',
    start_time: new Date().toISOString(),
    end_time: new Date().toISOString(),
    duration_ms: 150,
    metadata: {},
    total_tokens: 14,
    total_cost: 0.01,
    span_count: 4,
    error_count: 0,
    created_at: new Date().toISOString(),
  },
  {
    id: 'trace-c',
    name: 'Trace Gamma',
    status: 'success',
    start_time: new Date().toISOString(),
    end_time: new Date().toISOString(),
    duration_ms: 180,
    metadata: {},
    total_tokens: 9,
    total_cost: 0.003,
    span_count: 2,
    error_count: 1,
    created_at: new Date().toISOString(),
  },
]

const compareResponse = {
  trace_a_id: 'trace-a',
  trace_b_id: 'trace-b',
  summary: {
    status: 'mixed',
    regression_score: 11,
    signal_count: 0,
  },
  metrics: [],
  signals: [],
  top_actions: [],
}

const buildFetchMock = () => {
  const calls: string[] = []

  globalThis.fetch = vi.fn().mockImplementation((input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString()
    calls.push(url)

    if (url.includes('/api/v1/intelligence/compare')) {
      return createJsonResponse(compareResponse)
    }

    if (url.includes('/api/v1/traces/')) {
      const match = url.match(/\/api\/v1\/traces\/([^/?#]+)/)
      if (match) {
        const traceId = match[1]
        const trace = traces.find((item) => item.id === traceId)
        return createJsonResponse({
          trace,
          spans: [],
        })
      }
    }

    if (url.includes('/api/v1/traces?')) {
      return createJsonResponse({
        traces,
        total: traces.length,
        limit: 50,
        offset: 0,
      })
    }

    throw new Error(`Unexpected endpoint: ${url}`)
  })

  return calls
}

const createTracePreset = () => {
  return {
    id: 'saved-1',
    name: 'Nightly',
    traceA: 'trace-a',
    traceB: 'trace-c',
    createdAt: '2026-01-01T00:00:00.000Z',
  }
}

function createMockStorage() {
  const store = new Map<string, string>()

  return {
    clear() {
      store.clear()
    },
    getItem(key: string) {
      return store.get(key) || null
    },
    setItem(key: string, value: string) {
      store.set(key, value)
    },
    removeItem(key: string) {
      store.delete(key)
    },
  } as Storage
}

function expectTraceInSlot(slot: 'A' | 'B', traceName: string) {
  const selector = screen.getByTestId(`trace-selector-${slot.toLowerCase()}`)
  if (!selector) {
    throw new Error(`Expected selector container for trace ${slot}`)
  }
  expect(within(selector).getByText(traceName)).toBeInTheDocument()
}

describe('ComparisonPage comparison presets', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'localStorage', {
      value: createMockStorage(),
      configurable: true,
    })
    buildFetchMock()
  })

  afterEach(() => {
    window.localStorage.clear()
    vi.restoreAllMocks()
  })

  it('loads a preset from query param and selects trace pair', async () => {
    const calls = buildFetchMock()
    window.localStorage.setItem('compare_presets_v1', JSON.stringify([createTracePreset()]))

    renderWithProviders(<ComparisonPage />, ['/compare?preset=saved-1'])

    await waitFor(() => expectTraceInSlot('A', 'Trace Alpha'))
    expectTraceInSlot('A', 'Trace Alpha')
    expectTraceInSlot('B', 'Trace Gamma')
    expect(calls.some((url) => url.includes('/api/v1/intelligence/compare'))).toBe(true)
    expect(calls.some((url) => url.includes('/api/v1/traces/trace-a'))).toBe(true)
    expect(calls.some((url) => url.includes('/api/v1/traces/trace-c'))).toBe(true)
  })

  it('saves and renders compare presets from current selection', async () => {
    buildFetchMock()
    renderWithProviders(<ComparisonPage />, ['/compare?traceA=trace-a&traceB=trace-b'])

    await waitFor(() => expectTraceInSlot('A', 'Trace Alpha'))
    expectTraceInSlot('A', 'Trace Alpha')
    expectTraceInSlot('B', 'Trace Beta')

    const nameInput = screen.getByLabelText('Compare preset name')
    fireEvent.change(nameInput, { target: { value: 'Regression baseline' } })
    const saveButton = screen.getByRole('button', { name: 'Save preset' })

    fireEvent.click(saveButton)

    await waitFor(() => expect(screen.getByText('Regression baseline')).toBeInTheDocument())

    const stored = JSON.parse(window.localStorage.getItem('compare_presets_v1') || '[]')
    expect(stored).toHaveLength(1)
    expect(stored[0].name).toBe('Regression baseline')
  })

  it('loads and deletes a preset', async () => {
    window.localStorage.setItem(
      'compare_presets_v1',
      JSON.stringify([
        {
          id: 'saved-1',
          name: 'First preset',
          traceA: 'trace-b',
          traceB: 'trace-c',
          createdAt: '2026-01-02T00:00:00.000Z',
        },
      ])
    )

    buildFetchMock()
    renderWithProviders(<ComparisonPage />, ['/compare?traceA=trace-a&traceB=trace-b'])

    expect(await screen.findByText('First preset')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Load preset First preset' }))

    await waitFor(() => expectTraceInSlot('A', 'Trace Beta'))
    expectTraceInSlot('B', 'Trace Gamma')

    fireEvent.click(screen.getByRole('button', { name: 'Delete preset First preset' }))
    await waitFor(() => expect(screen.queryByText('First preset')).not.toBeInTheDocument())
  })
})
