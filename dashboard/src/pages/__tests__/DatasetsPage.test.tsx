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

      if (url.includes('/api/v1/datasets/builds') && method === 'GET') {
        return createJsonResponse({
          builds: [],
          total: 0,
          limit: 20,
          offset: 0,
          generated_at: new Date().toISOString(),
        })
      }

      if (url.includes('/api/v1/evals/suites') && method === 'GET') {
        return createJsonResponse({
          suites: [
            {
              id: 'suite-1',
              name: 'Saved suite',
              assertion_profile: 'balanced',
              source_trace_ids: ['trace-1'],
              case_count: 1,
              run_count: 0,
              created_at: new Date().toISOString(),
              updated_at: null,
            },
          ],
          total: 1,
          limit: 20,
          offset: 0,
          generated_at: new Date().toISOString(),
        })
      }

      if (
        url.includes('/api/v1/datasets/build') &&
        !url.includes('/api/v1/datasets/builds') &&
        method === 'POST'
      ) {
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

      if (url.includes('/api/v1/datasets/builds') && method === 'POST') {
        postedEndpoints.push('saved-dataset')
        return createJsonResponse({
          id: 'build-1',
          name: 'Saved build',
          format: 'chat',
          source_trace_ids: ['trace-1'],
          options: { include_raw: false },
          record_count: 1,
          skipped_count: 0,
          redaction_mode: 'redacted',
          created_at: new Date().toISOString(),
          artifact: {
            format: 'chat',
            record_count: 1,
            skipped_count: 0,
            records: [{ trace_id: 'trace-1', messages: [{ role: 'user', content: 'pricing' }] }],
            skipped: [],
            generated_at: new Date().toISOString(),
          },
        })
      }

      if (
        url.includes('/api/v1/evals/suite') &&
        !url.includes('/api/v1/evals/suites') &&
        method === 'POST'
      ) {
        postedEndpoints.push('eval')
        return createJsonResponse({
          name: 'Trace regression suite',
          assertion_profile: 'balanced',
          case_count: 1,
          cases: [{ source_trace_id: 'trace-1', assertions: [] }],
          generated_at: new Date().toISOString(),
        })
      }

      if (url.includes('/api/v1/evals/suites') && method === 'POST' && !url.includes('/runs')) {
        postedEndpoints.push('saved-eval')
        return createJsonResponse({
          id: 'suite-2',
          name: 'Trace regression suite',
          assertion_profile: 'balanced',
          source_trace_ids: ['trace-1'],
          case_count: 1,
          run_count: 0,
          created_at: new Date().toISOString(),
          updated_at: null,
          cases: [{ source_trace_id: 'trace-1', assertions: [] }],
          runs: [],
        }, 201)
      }

      if (url.includes('/api/v1/evals/suites') && url.includes('/runs') && method === 'POST') {
        postedEndpoints.push('eval-run')
        return createJsonResponse({
          id: 'run-1',
          suite_id: 'suite-1',
          name: 'Candidate run',
          candidate_trace_ids: ['trace-1'],
          passed: true,
          pass_count: 1,
          fail_count: 0,
          created_at: new Date().toISOString(),
          results: [{ candidate_trace_id: 'trace-1', passed: true }],
        }, 201)
      }

      throw new Error(`Unexpected fetch call: ${url}`)
    }) as unknown as typeof fetch

    renderWithProviders(<DatasetsPage />, ['/datasets'])

    expect(await screen.findByText('Pricing trace')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /select visible/i }))
    fireEvent.click(screen.getByRole('button', { name: /generate records/i }))

    await waitFor(() => expect(screen.getByText('Dataset Output')).toBeInTheDocument())
    expect(screen.getByText(/1 records/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /save redacted build/i }))
    await waitFor(() => expect(screen.getByText('Saved Dataset Build')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: /generate eval cases/i }))
    await waitFor(() => expect(screen.getByText('Eval Suite Output')).toBeInTheDocument())
    expect(screen.getAllByText(/1 cases/).length).toBeGreaterThan(0)

    fireEvent.click(screen.getByRole('button', { name: /save eval suite/i }))
    await waitFor(() => expect(screen.getByText('Saved Eval Suite')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: /record eval run/i }))
    await waitFor(() => expect(screen.getByText('Eval Run Result')).toBeInTheDocument())
    expect(postedEndpoints).toEqual(['dataset', 'saved-dataset', 'eval', 'saved-eval', 'eval-run'])
  })
})
