import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import IntelligencePage from '../IntelligencePage'
import { renderWithProviders } from '../../test/test-utils'

function createJsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('IntelligencePage triage workflow', () => {
  let originalFetch: typeof fetch

  beforeEach(() => {
    originalFetch = globalThis.fetch
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
    vi.restoreAllMocks()
  })

  it('runs compare context, failure modes, and regression explain with selected traces', async () => {
    let compareBody: Record<string, unknown> | null = null
    let failureBody: Record<string, unknown> | null = null
    let regressionBody: Record<string, unknown> | null = null
    let summaryBody: Record<string, unknown> | null = null

    globalThis.fetch = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString()

      if (url.includes('/api/v1/traces?')) {
        return createJsonResponse({
          traces: [
            {
              id: 'trace-a',
              name: 'Baseline trace',
              status: 'success',
              start_time: new Date().toISOString(),
              end_time: new Date().toISOString(),
              duration_ms: 100,
              metadata: {},
              total_tokens: 80,
              total_cost: 0.01,
              span_count: 2,
              error_count: 0,
              created_at: new Date().toISOString(),
            },
            {
              id: 'trace-b',
              name: 'Candidate trace',
              status: 'error',
              start_time: new Date().toISOString(),
              end_time: new Date().toISOString(),
              duration_ms: 300,
              metadata: {},
              total_tokens: 160,
              total_cost: 0.04,
              span_count: 4,
              error_count: 1,
              created_at: new Date().toISOString(),
            },
          ],
          total: 2,
          limit: 100,
          offset: 0,
        })
      }

      if (url.includes('/api/v1/intelligence/compare')) {
        compareBody = JSON.parse(String(init?.body ?? '{}'))
        return createJsonResponse({
          trace_a_id: 'trace-a',
          trace_b_id: 'trace-b',
          summary: { status: 'regressed', regression_score: 45, signal_count: 1 },
          metrics: [],
          signals: [
            {
              id: 'error-regression',
              title: 'Reliability Regression',
              severity: 'critical',
              kind: 'reliability',
              detail: 'Trace B has 1 more error span than Trace A.',
              recommendation: 'Fix erroring spans first.',
            },
          ],
          top_actions: [],
        })
      }

      if (url.includes('/api/v1/intelligence/failure-modes')) {
        failureBody = JSON.parse(String(init?.body ?? '{}'))
        return createJsonResponse({
          trace_id: 'trace-b',
          status: 'issue_detected',
          primary_mode: 'tool',
          confidence: 0.73,
          summary: "Primary failure mode is 'tool' with medium severity signals.",
          modes: [
            {
              mode: 'tool',
              score: 42,
              severity: 'medium',
              evidence_count: 1,
              evidence: [],
              recommendations: ['Validate tool inputs before invocation.'],
            },
          ],
        })
      }

      if (url.includes('/api/v1/intelligence/summary')) {
        summaryBody = JSON.parse(String(init?.body ?? '{}'))
        return createJsonResponse({
          trace_id: 'trace-b',
          baseline_trace_id: 'trace-a',
          triage_score: 52,
          triage_status: 'review',
          candidate_failure: { status: 'issue_detected', primary_mode: 'tool', confidence: 0.73 },
          candidate_anomaly: { status: 'degraded', anomaly_score: 32, anomaly_count: 1 },
          candidate_safety: { risk_level: 'low', risk_score: 0 },
          compare_summary: { status: 'regressed', regression_score: 45, signal_count: 1 },
          explanation: {
            status: 'regression_explained',
            hypothesis_count: 1,
            top_hypothesis_confidence: 0.88,
            summary: 'Generated 1 ranked root-cause hypotheses from deterministic signals.',
            hypotheses: [
              {
                id: 'reliability_regression',
                title: 'New reliability failures in candidate trace',
                confidence: 0.88,
                severity: 'high',
                evidence: [],
                recommendation: 'Fix erroring spans first.',
              },
            ],
          },
          generated_at: new Date().toISOString(),
          cached: true,
          cache_ttl_seconds: 120,
        })
      }

      if (url.includes('/api/v1/intelligence/regression-explain')) {
        regressionBody = JSON.parse(String(init?.body ?? '{}'))
        return createJsonResponse({
          trace_a_id: 'trace-a',
          trace_b_id: 'trace-b',
          compare_summary: { status: 'regressed', regression_score: 45, signal_count: 1 },
          candidate_failure: { status: 'issue_detected', primary_mode: 'tool', confidence: 0.73 },
          candidate_anomaly: { status: 'degraded', anomaly_score: 32, anomaly_count: 1 },
          candidate_safety: { risk_level: 'low', risk_score: 0 },
          explanation: {
            status: 'regression_explained',
            hypothesis_count: 1,
            top_hypothesis_confidence: 0.88,
            summary: 'Generated 1 ranked root-cause hypotheses from deterministic signals.',
            hypotheses: [
              {
                id: 'reliability_regression',
                title: 'New reliability failures in candidate trace',
                confidence: 0.88,
                severity: 'high',
                evidence: [],
                recommendation: 'Fix erroring spans first.',
              },
            ],
          },
        })
      }

      throw new Error(`Unexpected fetch call: ${url}`)
    }) as unknown as typeof fetch

    renderWithProviders(<IntelligencePage />, ['/intelligence'])

    await waitFor(() => {
      expect(screen.getByText('Intelligence Triage')).toBeInTheDocument()
      expect(screen.getByLabelText('Baseline Trace')).toBeInTheDocument()
    })

    fireEvent.change(screen.getByLabelText('Baseline Trace'), { target: { value: 'trace-a' } })
    fireEvent.change(screen.getByLabelText('Candidate Trace'), { target: { value: 'trace-b' } })

    fireEvent.click(screen.getByRole('button', { name: 'Load Summary' }))
    fireEvent.click(screen.getByRole('button', { name: 'Run Failure Modes' }))
    fireEvent.click(screen.getByRole('button', { name: 'Explain Regression' }))

    await waitFor(() => {
      expect(screen.getByText(/Summary Snapshot/)).toBeInTheDocument()
      expect(screen.getByText(/Regression score: 45/)).toBeInTheDocument()
      expect(screen.getByText(/Primary failure mode is 'tool'/)).toBeInTheDocument()
      expect(screen.getByText(/New reliability failures in candidate trace/)).toBeInTheDocument()
    })

    expect(compareBody).toEqual({ trace_a_id: 'trace-a', trace_b_id: 'trace-b' })
    expect(summaryBody).toEqual({
      trace_id: 'trace-b',
      baseline_trace_id: 'trace-a',
      history_limit: 20,
      refresh_cache: false,
    })
    expect(failureBody).toEqual({ trace_id: 'trace-b' })
    expect(regressionBody).toMatchObject({
      trace_a_id: 'trace-a',
      trace_b_id: 'trace-b',
    })
  })
})
