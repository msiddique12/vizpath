import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import IntelligencePanel from '../IntelligencePanel'
import { renderWithProviders } from '../../test/test-utils'

function createJsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('IntelligencePanel deterministic diagnostics', () => {
  let originalFetch: typeof fetch

  beforeEach(() => {
    originalFetch = globalThis.fetch
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
    vi.restoreAllMocks()
  })

  it('runs failure mode diagnostics and renders primary mode', async () => {
    let failureRequestBody: Record<string, unknown> | null = null
    globalThis.fetch = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/api/v1/intelligence/status')) {
        return createJsonResponse({
          nvidia_api_key_configured: false,
          model: 'nvidia/test-model',
          base_url: 'https://api.example.test',
        })
      }
      if (url.includes('/api/v1/intelligence/failure-modes')) {
        failureRequestBody = JSON.parse(String(init?.body ?? '{}'))
        return createJsonResponse({
          trace_id: 'trace-current',
          status: 'issue_detected',
          primary_mode: 'tool',
          confidence: 0.81,
          summary: "Primary failure mode is 'tool' with high severity signals.",
          modes: [
            {
              mode: 'tool',
              score: 68,
              severity: 'high',
              evidence_count: 2,
              evidence: [],
              recommendations: ['Validate tool inputs, permissions, and fallback behavior.'],
            },
          ],
        })
      }
      throw new Error(`Unexpected fetch call: ${url}`)
    }) as unknown as typeof fetch

    renderWithProviders(<IntelligencePanel traceId="trace-current" />)
    const button = await screen.findByRole('button', { name: 'Failure Modes' })
    fireEvent.click(button)

    await waitFor(() => {
      expect(screen.getByText(/Primary mode:/)).toBeInTheDocument()
      expect(screen.getByText(/tool · 68 · high/)).toBeInTheDocument()
    })
    expect(failureRequestBody).toEqual({ trace_id: 'trace-current' })
  })

  it('runs regression explain with baseline trace id', async () => {
    let regressionRequestBody: Record<string, unknown> | null = null
    globalThis.fetch = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/api/v1/intelligence/status')) {
        return createJsonResponse({
          nvidia_api_key_configured: true,
          model: 'nvidia/test-model',
          base_url: 'https://api.example.test',
        })
      }
      if (url.includes('/api/v1/intelligence/regression-explain')) {
        regressionRequestBody = JSON.parse(String(init?.body ?? '{}'))
        return createJsonResponse({
          trace_a_id: 'trace-baseline',
          trace_b_id: 'trace-current',
          compare_summary: { status: 'regressed', regression_score: 55, signal_count: 2 },
          candidate_failure: { status: 'issue_detected', primary_mode: 'infra', confidence: 0.77 },
          candidate_anomaly: { status: 'outlier', anomaly_score: 72, anomaly_count: 2 },
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
                evidence: ['Trace B has more error spans than Trace A.'],
                recommendation: 'Review erroring spans first; add retries/fallbacks only where deterministic.',
              },
            ],
          },
        })
      }
      throw new Error(`Unexpected fetch call: ${url}`)
    }) as unknown as typeof fetch

    renderWithProviders(<IntelligencePanel traceId="trace-current" />)
    const explainButton = await screen.findByRole('button', { name: 'Explain Regression' })
    expect(explainButton).toBeDisabled()

    fireEvent.change(screen.getByLabelText('Baseline Trace ID (for regression explain)'), {
      target: { value: 'trace-baseline' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Explain Regression' }))

    await waitFor(() => {
      expect(screen.getByText(/Regression Explain/)).toBeInTheDocument()
      expect(screen.getByText(/New reliability failures in candidate trace/)).toBeInTheDocument()
    })
    expect(regressionRequestBody).toMatchObject({
      trace_a_id: 'trace-baseline',
      trace_b_id: 'trace-current',
    })
  })
})
