import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AlertsPage from '../AlertsPage'
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

describe('AlertsPage', () => {
  let originalFetch: typeof fetch

  beforeEach(() => {
    originalFetch = globalThis.fetch
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
    vi.restoreAllMocks()
  })

  it('creates and evaluates alert rules', async () => {
    let createdBody: Record<string, unknown> | null = null
    let destinationBody: Record<string, unknown> | null = null
    const destinations: Array<Record<string, unknown>> = []
    let evaluateCalled = false
    const eventsRequestUrls: string[] = []

    globalThis.fetch = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = resolveUrl(input)
      const method = init?.method ?? 'GET'

      if (url.includes('/api/v1/projects/me/alerts/evaluate')) {
        evaluateCalled = true
        return createJsonResponse({
          generated_at: new Date().toISOString(),
          alert_count: 1,
          notifications_queued: 0,
          notifications_sent: 0,
          notifications_failed: 0,
          rules: [
            {
              id: 'rule-1',
              name: 'Error guardrail',
              metric: 'error_rate_percent',
              operator: 'gte',
              threshold: 5,
              window_days: 7,
              is_active: true,
              notification_cooldown_minutes: 60,
              last_triggered_at: new Date().toISOString(),
              last_notified_at: null,
              created_at: new Date().toISOString(),
              updated_at: null,
              current_value: 50,
              breached: true,
              notification_queued: false,
              notification_sent: false,
            },
          ],
          window_metrics: [
            {
              window_days: 7,
              trace_count: 2,
              error_rate_percent: 50,
              avg_duration_ms: 150,
              avg_tokens: 200,
              avg_cost: 0.02,
              total_tokens: 400,
              total_cost: 0.04,
            },
          ],
        })
      }

      if (url.includes('/api/v1/projects/me/alerts/ops-summary') && method === 'GET') {
        return createJsonResponse({
          window_days: 7,
          generated_at: new Date().toISOString(),
          queue_depth: 0,
          total_delivery_attempts: 1,
          notifications_sent: 1,
          notifications_failed: 0,
          notifications_queued: 0,
          delivery_success_rate: 100,
          replay_attempts: 0,
          replay_successes: 0,
          replay_failures: 0,
          replay_success_rate: 0,
          median_replay_seconds: null,
        })
      }

      if (url.includes('/api/v1/projects/me/alerts/events') && method === 'GET') {
        eventsRequestUrls.push(url)
        return createJsonResponse([
          {
            id: 'event-1',
            event_type: 'breach',
            rule_id: 'rule-1',
            destination_id: null,
            rule_name: 'Error guardrail',
            metric: 'error_rate_percent',
            operator: 'gte',
            threshold: 5,
            current_value: 50,
            message: 'Rule breached',
            created_at: new Date().toISOString(),
          },
        ])
      }

      if (url.includes('/api/v1/projects/me/alerts/dead-letter') && method === 'GET') {
        return createJsonResponse([])
      }

      if (url.includes('/api/v1/projects/me/alerts/destinations') && method === 'GET') {
        return createJsonResponse(destinations)
      }

      if (url.includes('/api/v1/projects/me/alerts/destinations') && method === 'POST') {
        destinationBody = JSON.parse(String(init?.body ?? '{}'))
        const createdDestination = {
          id: 'destination-1',
          name: destinationBody?.name,
          kind: 'webhook',
          target_url: destinationBody?.target_url,
          is_active: true,
          created_at: new Date().toISOString(),
          updated_at: null,
        }
        destinations.push(createdDestination)
        return createJsonResponse(createdDestination, 201)
      }

      if (url.includes('/api/v1/projects/me/alerts') && method === 'GET') {
        return createJsonResponse([
          {
            id: 'rule-1',
            name: 'Error guardrail',
            metric: 'error_rate_percent',
            operator: 'gte',
            threshold: 5,
            window_days: 7,
            is_active: true,
            notification_cooldown_minutes: 60,
            last_triggered_at: null,
            last_notified_at: null,
            created_at: new Date().toISOString(),
            updated_at: null,
          },
        ])
      }

      if (url.includes('/api/v1/projects/me/alerts') && method === 'POST') {
        createdBody = JSON.parse(String(init?.body ?? '{}'))
        return createJsonResponse({
          id: 'rule-2',
          name: createdBody?.name,
          metric: createdBody?.metric,
          operator: createdBody?.operator,
          threshold: createdBody?.threshold,
          window_days: createdBody?.window_days,
          is_active: true,
          notification_cooldown_minutes: createdBody?.notification_cooldown_minutes,
          last_triggered_at: null,
          last_notified_at: null,
          created_at: new Date().toISOString(),
          updated_at: null,
        })
      }

      if (url.includes('/api/v1/projects/me/alerts/') && method === 'PUT') {
        return createJsonResponse({
          id: 'rule-1',
          name: 'Error guardrail',
          metric: 'error_rate_percent',
          operator: 'gte',
          threshold: 5,
          window_days: 7,
          is_active: false,
          notification_cooldown_minutes: 60,
          last_triggered_at: null,
          last_notified_at: null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        })
      }

      if (url.includes('/api/v1/projects/me/alerts/') && method === 'DELETE') {
        return createJsonResponse({}, 204)
      }

      throw new Error(`Unexpected fetch call: ${url}`)
    }) as unknown as typeof fetch

    renderWithProviders(<AlertsPage />, ['/alerts'])

    await waitFor(() => {
      expect(screen.getAllByText('Error guardrail').length).toBeGreaterThan(0)
    })

    fireEvent.change(screen.getByLabelText('Rule name'), { target: { value: 'Cost spike' } })
    fireEvent.change(screen.getByLabelText('Alert metric'), { target: { value: 'avg_cost' } })
    fireEvent.change(screen.getByLabelText('Alert operator'), { target: { value: 'gt' } })
    fireEvent.change(screen.getByLabelText('Threshold'), { target: { value: '0.05' } })
    fireEvent.change(screen.getByLabelText('Window days'), { target: { value: '14' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add Rule' }))

    await waitFor(() => {
      expect(createdBody).toEqual({
        name: 'Cost spike',
        metric: 'avg_cost',
        operator: 'gt',
        threshold: 0.05,
        window_days: 14,
        is_active: true,
        notification_cooldown_minutes: 60,
      })
    })

    fireEvent.change(screen.getByLabelText('Destination name'), { target: { value: 'Ops webhook' } })
    fireEvent.change(screen.getByLabelText('Webhook URL'), {
      target: { value: 'https://hooks.example.com/ops' },
    })
    fireEvent.change(screen.getByLabelText('Secret token'), { target: { value: 'token-1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add Destination' }))

    await waitFor(() => {
      expect(destinationBody).toEqual({
        name: 'Ops webhook',
        kind: 'webhook',
        target_url: 'https://hooks.example.com/ops',
        secret_token: 'token-1',
        is_active: true,
      })
    })

    fireEvent.click(screen.getByRole('button', { name: 'Evaluate Rules' }))

    await waitFor(() => {
      expect(evaluateCalled).toBe(true)
      expect(screen.getByText('1 active alert detected.')).toBeInTheDocument()
      expect(screen.getByText(/Current: 50.00/)).toBeInTheDocument()
      expect(screen.getByText('Recent Alert Events')).toBeInTheDocument()
      expect(screen.getAllByText('Rule Breach').length).toBeGreaterThan(0)
    })

    fireEvent.change(screen.getByLabelText('Event type filter'), {
      target: { value: 'notification_failed' },
    })
    await waitFor(() => {
      expect(
        eventsRequestUrls.some((url) => url.includes('event_type=notification_failed'))
      ).toBe(true)
    })

    fireEvent.change(screen.getByLabelText('Event rule filter'), {
      target: { value: 'rule-1' },
    })
    await waitFor(() => {
      expect(
        eventsRequestUrls.some(
          (url) =>
            url.includes('event_type=notification_failed') && url.includes('rule_id=rule-1')
        )
      ).toBe(true)
    })
  })
})
