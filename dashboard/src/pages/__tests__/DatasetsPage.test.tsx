import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import DatasetsPage from '../DatasetsPage'
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

describe('DatasetsPage', () => {
  let originalFetch: typeof fetch

  beforeEach(() => {
    originalFetch = globalThis.fetch
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
    vi.restoreAllMocks()
  })

  it('builds dataset records and eval cases from selected traces', async () => {
    const postedEndpoints: string[] = []

    globalThis.fetch = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = resolveUrl(input)
      const method = init?.method ?? 'GET'

      if (url.includes('/api/v1/traces') && method === 'GET') {
        return createJsonResponse({
          traces: [
            {
              id: 'trace-1',
              name: 'Pricing trace',
              status: 'success',
              start_time: new Date().toISOString(),
              end_time: new Date().toISOString(),
              duration_ms: 1000,
              metadata: {},
              total_tokens: 500,
              total_cost: 0.03,
              span_count: 3,
              error_count: 0,
              created_at: new Date().toISOString(),
            },
          ],
          total: 1,
          limit: 100,
          offset: 0,
        })
      }

      if (url.includes('/api/v1/datasets/build') && method === 'POST') {
        postedEndpoints.push('dataset')
        return createJsonResponse({
          format: 'chat',
          record_count: 1,
          skipped_count: 0,
          records: [{ trace_id: 'trace-1', messages: [{ role: 'user', content: 'pricing' }] }],
          skipped: [],
          generated_at: new Date().toISOString(),
        })
      }

      if (url.includes('/api/v1/evals/suite') && method === 'POST') {
        postedEndpoints.push('eval')
        return createJsonResponse({
          name: 'Trace regression suite',
          assertion_profile: 'balanced',
          case_count: 1,
          cases: [{ source_trace_id: 'trace-1', assertions: [] }],
          generated_at: new Date().toISOString(),
        })
      }

      throw new Error(`Unexpected fetch call: ${url}`)
    }) as unknown as typeof fetch

    renderWithProviders(<DatasetsPage />, ['/datasets'])

    expect(await screen.findByText('Pricing trace')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /select visible/i }))
    fireEvent.click(screen.getByRole('button', { name: /generate records/i }))

    await waitFor(() => expect(screen.getByText('Dataset Output')).toBeInTheDocument())
    expect(screen.getByText(/1 records/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /generate eval cases/i }))
    await waitFor(() => expect(screen.getByText('Eval Suite Output')).toBeInTheDocument())
    expect(screen.getByText(/1 cases/)).toBeInTheDocument()
    expect(postedEndpoints).toEqual(['dataset', 'eval'])
  })
})
