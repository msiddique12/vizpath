import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import FailureInboxPage from '../FailureInboxPage'
import { renderWithProviders } from '../../test/test-utils'

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

describe('FailureInboxPage', () => {
  let originalFetch: typeof fetch

  beforeEach(() => {
    originalFetch = globalThis.fetch
    globalThis.fetch = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = resolveUrl(input)
      const method = init?.method ?? (input instanceof Request ? input.method : 'GET')

      if (url.includes('/curation/labels') && method === 'POST') {
        const body = typeof init?.body === 'string' ? JSON.parse(init.body) : {}
        return createJsonResponse({
          trace_id: body.trace_id ?? 'trace-timeout',
          label: body.label ?? null,
          quality_score: null,
          notes: null,
          exported: false,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        })
      }

      if (url.includes('/triage/items') && method === 'GET') {
        return createJsonResponse({
          items: [
            {
              id: 'triage-timeout',
              trace_id: 'trace-timeout',
              trace_name: 'Timeout while calling api',
              trace_status: 'error',
              status: 'open',
              priority: 'high',
              owner: null,
              failure_mode: 'Timeout / slow execution',
              title: 'Timeout while calling api',
              notes: null,
              linked_trace_ids: [],
              resolved_at: null,
              resolved_by: null,
              created_at: new Date().toISOString(),
              updated_at: null,
            },
          ],
          total: 1,
          limit: 300,
          offset: 0,
          generated_at: new Date().toISOString(),
        })
      }

      if (url.includes('/triage/items') && method === 'POST') {
        const body = typeof init?.body === 'string' ? JSON.parse(init.body) : {}
        return createJsonResponse({
          id: 'triage-created',
          trace_id: body.trace_id,
          trace_name: 'JSON parse failure',
          trace_status: 'error',
          status: body.status ?? 'open',
          priority: body.priority ?? 'high',
          owner: null,
          failure_mode: body.failure_mode ?? null,
          title: body.title ?? 'JSON parse failure',
          notes: null,
          linked_trace_ids: [],
          resolved_at: null,
          resolved_by: null,
          created_at: new Date().toISOString(),
          updated_at: null,
        })
      }

      if (url.includes('/curation/traces')) {
        return createJsonResponse([
          {
            trace_id: 'trace-timeout',
            trace_name: 'Timeout while calling api',
            label: 'needs_improvement',
            quality_score: null,
            notes: null,
            exported: false,
            span_count: 4,
            total_tokens: 430,
            duration_ms: 35000,
          },
        ])
      }

      return createJsonResponse({
        traces: [
          {
            id: 'trace-timeout',
            name: 'Timeout while calling api',
            status: 'error',
            start_time: new Date().toISOString(),
            end_time: new Date().toISOString(),
            duration_ms: 35000,
            metadata: { error: 'timeout from upstream API' },
            total_tokens: 430,
            total_cost: 0.01,
            span_count: 4,
            error_count: 2,
            created_at: new Date().toISOString(),
          },
          {
            id: 'trace-parse',
            name: 'JSON parse failure',
            status: 'error',
            start_time: new Date().toISOString(),
            end_time: new Date().toISOString(),
            duration_ms: 1200,
            metadata: { error: 'schema parse exception' },
            total_tokens: 900,
            total_cost: 0.03,
            span_count: 9,
            error_count: 1,
            created_at: new Date().toISOString(),
          },
        ],
        total: 2,
        limit: 150,
        offset: 0,
      })
    }) as unknown as typeof fetch
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  it('groups failures and supports one-click triage creation', async () => {
    renderWithProviders(<FailureInboxPage />, ['/inbox'])

    await waitFor(() => expect(screen.getByText('Failure Inbox')).toBeInTheDocument())
    expect(screen.getByText('Timeout / slow execution')).toBeInTheDocument()
    expect(screen.getByText('Output parsing failure')).toBeInTheDocument()
    expect(screen.getByText('Label: needs_improvement')).toBeInTheDocument()
    expect(screen.getByText('Triage: open')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Open triage item for trace trace-parse' }))

    await waitFor(() => {
      const calls = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls
      const triageCall = calls.find(([input, init]) => {
        const url = resolveUrl(input as RequestInfo | URL)
        if (!url.includes('/triage/items') || (init as RequestInit | undefined)?.method !== 'POST') {
          return false
        }
        const body = typeof (init as RequestInit | undefined)?.body === 'string'
          ? JSON.parse((init as RequestInit).body as string)
          : {}
        return body.trace_id === 'trace-parse' && body.status === 'open'
      })

      expect(triageCall).toBeDefined()
    })
  })
})
