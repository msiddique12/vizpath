import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import OperationsPage from '../OperationsPage'
import { renderWithProviders } from '../../test/test-utils'

function createJsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function resolveUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input
  if (input instanceof URL) return input.toString()
  return input.url
}

const tracePayload = {
  id: 'trace-ops-1',
  name: 'Ops pricing trace',
  status: 'success',
  start_time: new Date().toISOString(),
  end_time: new Date().toISOString(),
  duration_ms: 900,
  metadata: {},
  total_tokens: 420,
  total_cost: 0.02,
  span_count: 3,
  error_count: 0,
  created_at: new Date().toISOString(),
}

describe('OperationsPage', () => {
  let originalFetch: typeof fetch

  beforeEach(() => {
    originalFetch = globalThis.fetch
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
    vi.restoreAllMocks()
  })

  it('shows scorecards, runs search, and evaluates guardrails', async () => {
    let searchCalled = false
    let guardrailsCalled = false

    globalThis.fetch = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = resolveUrl(input)
      const method = init?.method ?? 'GET'

      if (url.includes('/api/v1/analytics/scorecard')) {
        return createJsonResponse({
          window_days: 7,
          trace_count: 4,
          success_count: 3,
          error_count: 1,
          running_count: 0,
          reliability_score: 75,
          p50_duration_ms: 500,
          p95_duration_ms: 1200,
          total_tokens: 2000,
          total_cost: 0.12,
          avg_tokens_per_trace: 500,
          avg_cost_per_trace: 0.03,
          tool_success_rate: 80,
          llm_call_count: 4,
          tool_call_count: 5,
        })
      }

      if (url.includes('/api/v1/analytics/tools')) {
        return createJsonResponse({
          window_days: 7,
          tool_count: 1,
          tools: [
            {
              name: 'tool.search',
              call_count: 5,
              success_count: 4,
              error_count: 1,
              success_rate: 80,
              avg_duration_ms: 300,
              total_tokens: 0,
              total_cost: 0,
            },
          ],
          generated_at: new Date().toISOString(),
        })
      }

      if (url.includes('/api/v1/traces') && method === 'GET') {
        return createJsonResponse({ traces: [tracePayload], total: 1, limit: 100, offset: 0 })
      }

      if (url.includes('/api/v1/guardrails/defaults')) {
        return createJsonResponse({
          policies: [
            {
              id: 'trace-errors',
              name: 'No error spans',
              metric: 'error_count',
              operator: 'eq',
              threshold: 0,
              severity: 'critical',
            },
          ],
        })
      }

      if (url.includes('/api/v1/search/traces') && method === 'POST') {
        searchCalled = true
        return createJsonResponse({
          query: 'pricing',
          result_count: 1,
          results: [
            {
              trace: tracePayload,
              score: 2,
              matched_terms: ['pricing'],
              matched_spans: [{ span_id: 'span-1', name: 'tool.search', span_type: 'tool', matched_terms: ['pricing'] }],
            },
          ],
          generated_at: new Date().toISOString(),
        })
      }

      if (url.includes('/api/v1/guardrails/evaluate') && method === 'POST') {
        guardrailsCalled = true
        return createJsonResponse({
          trace_count: 1,
          policy_count: 1,
          breach_count: 0,
          results: [
            {
              trace_id: 'trace-ops-1',
              trace_name: 'Ops pricing trace',
              status: 'success',
              passed: true,
              metrics: { error_count: 0 },
              policies: [
                {
                  policy_id: 'trace-errors',
                  name: 'No error spans',
                  metric: 'error_count',
                  operator: 'eq',
                  threshold: 0,
                  current_value: 0,
                  passed: true,
                  severity: 'critical',
                },
              ],
            },
          ],
          generated_at: new Date().toISOString(),
        })
      }

      throw new Error(`Unexpected fetch call: ${url}`)
    }) as unknown as typeof fetch

    renderWithProviders(<OperationsPage />, ['/operations'])

    expect(await screen.findByText('75.0%')).toBeInTheDocument()
    expect(screen.getByText('tool.search')).toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText('tool timeout pricing'), {
      target: { value: 'pricing' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))

    await waitFor(() => expect(searchCalled).toBe(true))
    expect(screen.getAllByText('Ops pricing trace').length).toBeGreaterThan(0)

    fireEvent.click(screen.getByRole('button', { name: 'Evaluate' }))
    await waitFor(() => expect(guardrailsCalled).toBe(true))
    expect(screen.getByText(/0 breaches across 1 traces/)).toBeInTheDocument()
  })
})
