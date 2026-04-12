import { FormEvent, useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, BellRing, Loader2, ShieldCheck, Trash2, Webhook } from 'lucide-react'
import clsx from 'clsx'
import {
  AlertEventType,
  AlertMetric,
  AlertOperator,
  createAlertDestination,
  createAlertRule,
  deleteAlertDestination,
  deleteAlertRule,
  evaluateAlertRules,
  getAlertDeadLetters,
  getAlertDestinations,
  getAlertEvents,
  getAlertOpsSummary,
  getAlertOpsTrends,
  getAlertRules,
  replayAlertDeadLetter,
  updateAlertDestination,
  updateAlertRule,
} from '@/lib/api'

const METRIC_OPTIONS: Array<{ value: AlertMetric; label: string; help: string }> = [
  { value: 'error_rate_percent', label: 'Error Rate (%)', help: 'Percent of traces with errors' },
  { value: 'avg_duration_ms', label: 'Avg Duration (ms)', help: 'Average trace runtime' },
  { value: 'avg_tokens', label: 'Avg Tokens', help: 'Average tokens per trace' },
  { value: 'avg_cost', label: 'Avg Cost ($)', help: 'Average cost per trace' },
  { value: 'trace_count', label: 'Trace Count', help: 'Total traces in window' },
  { value: 'total_tokens', label: 'Total Tokens', help: 'Total tokens in window' },
  { value: 'total_cost', label: 'Total Cost ($)', help: 'Total cost in window' },
]

const OPERATOR_OPTIONS: Array<{ value: AlertOperator; label: string }> = [
  { value: 'gt', label: '>' },
  { value: 'gte', label: '>=' },
  { value: 'lt', label: '<' },
  { value: 'lte', label: '<=' },
]

const EVENTS_PAGE_SIZE = 25

const EVENT_TYPE_OPTIONS: Array<{ value: AlertEventType; label: string }> = [
  { value: 'breach', label: 'Rule Breach' },
  { value: 'notification_queued', label: 'Notification Queued' },
  { value: 'notification_sent', label: 'Notification Sent' },
  { value: 'notification_failed', label: 'Notification Failed' },
  { value: 'notification_replayed', label: 'Notification Replayed' },
  { value: 'notification_replay_failed', label: 'Replay Failed' },
]

function formatMetric(metric: AlertMetric): string {
  return METRIC_OPTIONS.find((option) => option.value === metric)?.label ?? metric
}

function formatEventType(eventType: AlertEventType): string {
  if (eventType === 'breach') return 'Rule Breach'
  if (eventType === 'notification_queued') return 'Notification Queued'
  if (eventType === 'notification_sent') return 'Notification Sent'
  if (eventType === 'notification_replayed') return 'Notification Replayed'
  if (eventType === 'notification_replay_failed') return 'Replay Failed'
  return 'Notification Failed'
}

export default function AlertsPage() {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [metric, setMetric] = useState<AlertMetric>('error_rate_percent')
  const [operator, setOperator] = useState<AlertOperator>('gte')
  const [threshold, setThreshold] = useState('5')
  const [windowDays, setWindowDays] = useState('7')
  const [cooldownMinutes, setCooldownMinutes] = useState('60')

  const [destinationName, setDestinationName] = useState('')
  const [destinationUrl, setDestinationUrl] = useState('')
  const [destinationToken, setDestinationToken] = useState('')
  const [eventTypeFilter, setEventTypeFilter] = useState<AlertEventType | 'all'>('all')
  const [eventRuleFilter, setEventRuleFilter] = useState<string>('all')
  const [eventOffset, setEventOffset] = useState(0)
  const [opsWindowDays, setOpsWindowDays] = useState<7 | 30>(7)

  const [formError, setFormError] = useState<string | null>(null)
  const [destinationError, setDestinationError] = useState<string | null>(null)
  const [actionStatus, setActionStatus] = useState<string | null>(null)

  const rulesQuery = useQuery({
    queryKey: ['alerts-rules'],
    queryFn: getAlertRules,
  })

  const destinationsQuery = useQuery({
    queryKey: ['alerts-destinations'],
    queryFn: getAlertDestinations,
  })

  const eventsQuery = useQuery({
    queryKey: ['alerts-events', eventTypeFilter, eventRuleFilter, eventOffset],
    queryFn: () =>
      getAlertEvents({
        limit: EVENTS_PAGE_SIZE,
        offset: eventOffset,
        event_type: eventTypeFilter === 'all' ? undefined : eventTypeFilter,
        rule_id: eventRuleFilter === 'all' ? undefined : eventRuleFilter,
      }),
  })

  const deadLettersQuery = useQuery({
    queryKey: ['alerts-dead-letter'],
    queryFn: () => getAlertDeadLetters({ limit: 25 }),
  })

  const opsSummaryQuery = useQuery({
    queryKey: ['alerts-ops-summary', opsWindowDays],
    queryFn: () => getAlertOpsSummary(opsWindowDays),
  })
  const opsTrendsQuery = useQuery({
    queryKey: ['alerts-ops-trends', opsWindowDays],
    queryFn: () => getAlertOpsTrends(opsWindowDays),
  })

  const createRuleMutation = useMutation({
    mutationFn: createAlertRule,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts-rules'] })
      queryClient.invalidateQueries({ queryKey: ['alerts-events'] })
      setActionStatus('Alert rule created.')
      setName('')
      setFormError(null)
    },
    onError: () => setActionStatus('Failed to create alert rule.'),
  })

  const evaluateMutation = useMutation({
    mutationFn: ({ notify }: { notify: boolean }) =>
      evaluateAlertRules({
        persist: true,
        notify,
      }),
    onSuccess: (data, variables) => {
      const notificationSummary = variables.notify
        ? ` Notifications queued: ${data.notifications_queued}, sent: ${data.notifications_sent}, failed: ${data.notifications_failed}.`
        : ''
      setActionStatus(`Rules evaluated.${notificationSummary}`)
      queryClient.invalidateQueries({ queryKey: ['alerts-rules'] })
      queryClient.invalidateQueries({ queryKey: ['alerts-events'] })
    },
    onError: () => setActionStatus('Failed to evaluate alert rules.'),
  })

  const createDestinationMutation = useMutation({
    mutationFn: createAlertDestination,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts-destinations'] })
      queryClient.invalidateQueries({ queryKey: ['alerts-events'] })
      setActionStatus('Alert destination created.')
      setDestinationName('')
      setDestinationUrl('')
      setDestinationToken('')
      setDestinationError(null)
    },
    onError: () => setActionStatus('Failed to create alert destination.'),
  })

  const toggleMutation = useMutation({
    mutationFn: ({ ruleId, isActive }: { ruleId: string; isActive: boolean }) =>
      updateAlertRule(ruleId, { is_active: isActive }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts-rules'] })
      queryClient.invalidateQueries({ queryKey: ['alerts-events'] })
      setActionStatus('Rule updated.')
    },
    onError: () => setActionStatus('Failed to update rule.'),
  })

  const deleteMutation = useMutation({
    mutationFn: deleteAlertRule,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts-rules'] })
      queryClient.invalidateQueries({ queryKey: ['alerts-events'] })
      setActionStatus('Rule deleted.')
    },
    onError: () => setActionStatus('Failed to delete rule.'),
  })

  const toggleDestinationMutation = useMutation({
    mutationFn: ({ destinationId, isActive }: { destinationId: string; isActive: boolean }) =>
      updateAlertDestination(destinationId, { is_active: isActive }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts-destinations'] })
      queryClient.invalidateQueries({ queryKey: ['alerts-events'] })
      setActionStatus('Destination updated.')
    },
    onError: () => setActionStatus('Failed to update destination.'),
  })

  const deleteDestinationMutation = useMutation({
    mutationFn: deleteAlertDestination,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts-destinations'] })
      queryClient.invalidateQueries({ queryKey: ['alerts-events'] })
      setActionStatus('Destination deleted.')
    },
    onError: () => setActionStatus('Failed to delete destination.'),
  })

  const replayDeadLetterMutation = useMutation({
    mutationFn: replayAlertDeadLetter,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['alerts-dead-letter'] })
      queryClient.invalidateQueries({ queryKey: ['alerts-events'] })
      setActionStatus(data.message)
    },
    onError: () => setActionStatus('Failed to replay dead-letter alert.'),
  })

  const rules = rulesQuery.data ?? []
  const destinations = destinationsQuery.data ?? []
  const events = eventsQuery.data ?? []
  const hasNextEventsPage = events.length === EVENTS_PAGE_SIZE
  const deadLetters = deadLettersQuery.data ?? []
  const opsSummary = opsSummaryQuery.data
  const opsTrendSeries = opsTrendsQuery.data?.series ?? []
  const recentTrendPoints = opsTrendSeries.slice(-7)
  const maxTrendAttempts = Math.max(
    ...recentTrendPoints.map((point) => point.delivery_attempts),
    1
  )
  const activeDestinations = destinations.filter((destination) => destination.is_active)
  const evaluatedRules = useMemo(() => evaluateMutation.data?.rules ?? [], [evaluateMutation.data?.rules])
  const evaluatedById = useMemo(
    () => new Map(evaluatedRules.map((rule) => [rule.id, rule])),
    [evaluatedRules]
  )

  useEffect(() => {
    setEventOffset(0)
  }, [eventTypeFilter, eventRuleFilter])

  const handleCreateRule = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const thresholdValue = Number(threshold)
    const windowValue = Number(windowDays)
    const cooldownValue = Number(cooldownMinutes)
    if (!name.trim()) {
      setFormError('Rule name is required.')
      return
    }
    if (Number.isNaN(thresholdValue)) {
      setFormError('Threshold must be numeric.')
      return
    }
    if (!Number.isInteger(windowValue) || windowValue < 1 || windowValue > 90) {
      setFormError('Window days must be an integer between 1 and 90.')
      return
    }
    if (!Number.isInteger(cooldownValue) || cooldownValue < 0 || cooldownValue > 10080) {
      setFormError('Cooldown must be an integer between 0 and 10080 minutes.')
      return
    }

    createRuleMutation.mutate({
      name: name.trim(),
      metric,
      operator,
      threshold: thresholdValue,
      window_days: windowValue,
      is_active: true,
      notification_cooldown_minutes: cooldownValue,
    })
  }

  const handleCreateDestination = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!destinationName.trim()) {
      setDestinationError('Destination name is required.')
      return
    }
    if (!destinationUrl.trim()) {
      setDestinationError('Webhook URL is required.')
      return
    }

    createDestinationMutation.mutate({
      name: destinationName.trim(),
      kind: 'webhook',
      target_url: destinationUrl.trim(),
      secret_token: destinationToken.trim() || undefined,
      is_active: true,
    })
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-muted-100 flex items-center gap-2">
          <BellRing className="h-6 w-6 text-primary-400" />
          Alerts & SLOs
        </h1>
        <p className="mt-1 text-sm text-muted-400">
          Define per-project guardrails for reliability, latency, and cost.
        </p>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={() => setOpsWindowDays(7)}
            className={clsx(
              'px-2.5 py-1 text-xs rounded border transition-colors',
              opsWindowDays === 7
                ? 'border-primary-500 bg-primary-900/30 text-primary-200'
                : 'border-dark-700 text-muted-400 hover:bg-dark-800'
            )}
          >
            7d
          </button>
          <button
            type="button"
            onClick={() => setOpsWindowDays(30)}
            className={clsx(
              'px-2.5 py-1 text-xs rounded border transition-colors',
              opsWindowDays === 30
                ? 'border-primary-500 bg-primary-900/30 text-primary-200'
                : 'border-dark-700 text-muted-400 hover:bg-dark-800'
            )}
          >
            30d
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="bg-dark-900 rounded-lg border border-dark-700 p-3">
          <p className="text-xs text-muted-400">Delivery Success ({opsWindowDays}d)</p>
          <p className="text-lg font-semibold text-muted-100 mt-1">
            {opsSummary ? `${opsSummary.delivery_success_rate.toFixed(1)}%` : '...'}
          </p>
          <p className="text-xs text-muted-500 mt-1">
            {opsSummary
              ? `${opsSummary.notifications_sent} sent / ${opsSummary.total_delivery_attempts} attempts`
              : 'Loading'}
          </p>
        </div>
        <div className="bg-dark-900 rounded-lg border border-dark-700 p-3">
          <p className="text-xs text-muted-400">Replay Success ({opsWindowDays}d)</p>
          <p className="text-lg font-semibold text-muted-100 mt-1">
            {opsSummary ? `${opsSummary.replay_success_rate.toFixed(1)}%` : '...'}
          </p>
          <p className="text-xs text-muted-500 mt-1">
            {opsSummary
              ? `${opsSummary.replay_successes} success / ${opsSummary.replay_attempts} replays`
              : 'Loading'}
          </p>
        </div>
        <div className="bg-dark-900 rounded-lg border border-dark-700 p-3">
          <p className="text-xs text-muted-400">Queue Depth</p>
          <p className="text-lg font-semibold text-muted-100 mt-1">
            {opsSummary ? opsSummary.queue_depth : '...'}
          </p>
          <p className="text-xs text-muted-500 mt-1">Current async notification queue size</p>
        </div>
        <div className="bg-dark-900 rounded-lg border border-dark-700 p-3">
          <p className="text-xs text-muted-400">Median Replay Latency</p>
          <p className="text-lg font-semibold text-muted-100 mt-1">
            {opsSummary && opsSummary.median_replay_seconds !== null
              ? `${opsSummary.median_replay_seconds.toFixed(1)}s`
              : 'n/a'}
          </p>
          <p className="text-xs text-muted-500 mt-1">Time from failure event to replay attempt</p>
        </div>
      </div>

      <div className="bg-dark-900 rounded-lg border border-dark-700 p-3">
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs text-muted-400">Daily Delivery Trend ({opsWindowDays}d window)</p>
          <p className="text-xs text-muted-500">Last 7 days</p>
        </div>
        {opsTrendsQuery.isLoading ? (
          <div className="flex items-center gap-2 text-xs text-muted-500 mt-3">
            <Loader2 className="h-3 w-3 animate-spin" />
            Loading trend...
          </div>
        ) : recentTrendPoints.length === 0 ? (
          <p className="text-xs text-muted-500 mt-3">No trend data yet.</p>
        ) : (
          <div className="mt-3 space-y-2">
            {recentTrendPoints.map((point) => (
              <div key={point.date} className="grid grid-cols-[90px_1fr_auto] items-center gap-2">
                <p className="text-xs text-muted-400">{point.date.slice(5)}</p>
                <div className="h-2 rounded bg-dark-800 overflow-hidden">
                  <div
                    className="h-full bg-primary-500/80"
                    style={{
                      width: `${Math.max(
                        6,
                        Math.round((point.delivery_attempts / maxTrendAttempts) * 100)
                      )}%`,
                    }}
                  />
                </div>
                <p className="text-xs text-muted-300">
                  {point.notifications_sent}/{point.delivery_attempts}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="bg-dark-900 rounded-lg border border-dark-700 p-4 space-y-4">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <h2 className="text-sm font-medium text-muted-200">Create Alert Rule</h2>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => evaluateMutation.mutate({ notify: false })}
              disabled={evaluateMutation.isPending || rules.length === 0}
              className={clsx(
                'inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm border transition-colors',
                evaluateMutation.isPending || rules.length === 0
                  ? 'bg-dark-800 border-dark-700 text-muted-500 cursor-not-allowed'
                  : 'bg-dark-800 border-dark-700 text-muted-200 hover:bg-dark-700'
              )}
            >
              {evaluateMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <ShieldCheck className="h-4 w-4" />
              )}
              Evaluate Rules
            </button>
            <button
              type="button"
              onClick={() => evaluateMutation.mutate({ notify: true })}
              disabled={evaluateMutation.isPending || rules.length === 0 || activeDestinations.length === 0}
              className={clsx(
                'inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm border transition-colors',
                evaluateMutation.isPending || rules.length === 0 || activeDestinations.length === 0
                  ? 'bg-dark-800 border-dark-700 text-muted-500 cursor-not-allowed'
                  : 'bg-primary-600 border-primary-500 text-white hover:bg-primary-700'
              )}
            >
              <Webhook className="h-4 w-4" />
              Evaluate + Notify
            </button>
          </div>
        </div>

        <form onSubmit={handleCreateRule} className="grid grid-cols-1 md:grid-cols-6 gap-2">
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Rule name"
            className="md:col-span-2 rounded-lg border border-dark-700 bg-dark-800 px-3 py-2 text-sm text-muted-100 placeholder:text-muted-500 focus:outline-none focus:ring-2 focus:ring-primary-500"
            aria-label="Rule name"
          />
          <select
            value={metric}
            onChange={(event) => setMetric(event.target.value as AlertMetric)}
            className="rounded-lg border border-dark-700 bg-dark-800 px-3 py-2 text-sm text-muted-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
            aria-label="Alert metric"
          >
            {METRIC_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <div className="flex gap-2">
            <select
              value={operator}
              onChange={(event) => setOperator(event.target.value as AlertOperator)}
              className="w-20 rounded-lg border border-dark-700 bg-dark-800 px-3 py-2 text-sm text-muted-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
              aria-label="Alert operator"
            >
              {OPERATOR_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <input
              value={threshold}
              onChange={(event) => setThreshold(event.target.value)}
              className="flex-1 rounded-lg border border-dark-700 bg-dark-800 px-3 py-2 text-sm text-muted-100 placeholder:text-muted-500 focus:outline-none focus:ring-2 focus:ring-primary-500"
              placeholder="Threshold"
              aria-label="Threshold"
            />
          </div>
          <input
            value={windowDays}
            onChange={(event) => setWindowDays(event.target.value)}
            className="rounded-lg border border-dark-700 bg-dark-800 px-3 py-2 text-sm text-muted-100 placeholder:text-muted-500 focus:outline-none focus:ring-2 focus:ring-primary-500"
            placeholder="Window days"
            aria-label="Window days"
          />
          <div className="flex gap-2">
            <input
              value={cooldownMinutes}
              onChange={(event) => setCooldownMinutes(event.target.value)}
              className="w-28 rounded-lg border border-dark-700 bg-dark-800 px-3 py-2 text-sm text-muted-100 placeholder:text-muted-500 focus:outline-none focus:ring-2 focus:ring-primary-500"
              placeholder="Cooldown"
              aria-label="Cooldown mins"
            />
            <button
              type="submit"
              disabled={createRuleMutation.isPending}
              className={clsx(
                'flex-1 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                createRuleMutation.isPending
                  ? 'bg-dark-700 text-muted-500 cursor-not-allowed'
                  : 'bg-primary-600 text-white hover:bg-primary-700'
              )}
            >
              {createRuleMutation.isPending ? 'Creating...' : 'Add Rule'}
            </button>
          </div>
        </form>

        <p className="text-xs text-muted-400">
          {METRIC_OPTIONS.find((option) => option.value === metric)?.help}
        </p>
        {formError && <p className="text-xs text-red-400">{formError}</p>}
        {actionStatus && <p className="text-xs text-primary-300">{actionStatus}</p>}
      </div>

      <div className="bg-dark-900 rounded-lg border border-dark-700 p-4 space-y-4">
        <h2 className="text-sm font-medium text-muted-200 flex items-center gap-2">
          <Webhook className="h-4 w-4 text-primary-400" />
          Alert Destinations
        </h2>
        <form onSubmit={handleCreateDestination} className="grid grid-cols-1 md:grid-cols-4 gap-2">
          <input
            value={destinationName}
            onChange={(event) => setDestinationName(event.target.value)}
            placeholder="Destination name"
            aria-label="Destination name"
            className="rounded-lg border border-dark-700 bg-dark-800 px-3 py-2 text-sm text-muted-100 placeholder:text-muted-500 focus:outline-none focus:ring-2 focus:ring-primary-500"
          />
          <input
            value={destinationUrl}
            onChange={(event) => setDestinationUrl(event.target.value)}
            placeholder="https://example.com/webhook"
            aria-label="Webhook URL"
            className="rounded-lg border border-dark-700 bg-dark-800 px-3 py-2 text-sm text-muted-100 placeholder:text-muted-500 focus:outline-none focus:ring-2 focus:ring-primary-500"
          />
          <input
            value={destinationToken}
            onChange={(event) => setDestinationToken(event.target.value)}
            placeholder="Optional bearer token"
            aria-label="Secret token"
            className="rounded-lg border border-dark-700 bg-dark-800 px-3 py-2 text-sm text-muted-100 placeholder:text-muted-500 focus:outline-none focus:ring-2 focus:ring-primary-500"
          />
          <button
            type="submit"
            disabled={createDestinationMutation.isPending}
            className={clsx(
              'rounded-lg px-3 py-2 text-sm font-medium transition-colors',
              createDestinationMutation.isPending
                ? 'bg-dark-700 text-muted-500 cursor-not-allowed'
                : 'bg-primary-600 text-white hover:bg-primary-700'
            )}
          >
            {createDestinationMutation.isPending ? 'Creating...' : 'Add Destination'}
          </button>
        </form>
        {destinationError && <p className="text-xs text-red-400">{destinationError}</p>}
        {destinationsQuery.isLoading ? (
          <div className="flex items-center justify-center h-16">
            <Loader2 className="h-5 w-5 text-primary-500 animate-spin" />
          </div>
        ) : destinations.length === 0 ? (
          <p className="text-sm text-muted-400">No alert destinations configured.</p>
        ) : (
          <div className="divide-y divide-dark-700 rounded-lg border border-dark-700 bg-dark-800">
            {destinations.map((destination) => (
              <div
                key={destination.id}
                className="px-3 py-2 flex items-center justify-between gap-2 flex-wrap"
              >
                <div className="min-w-0">
                  <p className="text-sm text-muted-100">{destination.name}</p>
                  <p className="text-xs text-muted-400 truncate">{destination.target_url}</p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() =>
                      toggleDestinationMutation.mutate({
                        destinationId: destination.id,
                        isActive: !destination.is_active,
                      })
                    }
                    disabled={toggleDestinationMutation.isPending}
                    className={clsx(
                      'px-2.5 py-1 text-xs rounded border',
                      destination.is_active
                        ? 'border-emerald-700 text-emerald-300 hover:bg-emerald-900/20'
                        : 'border-amber-700 text-amber-300 hover:bg-amber-900/20'
                    )}
                  >
                    {destination.is_active ? 'Active' : 'Paused'}
                  </button>
                  <button
                    type="button"
                    onClick={() => deleteDestinationMutation.mutate(destination.id)}
                    disabled={deleteDestinationMutation.isPending}
                    className="inline-flex items-center gap-1 px-2.5 py-1 text-xs rounded border border-red-700 text-red-300 hover:bg-red-900/20"
                  >
                    <Trash2 className="h-3 w-3" />
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {evaluateMutation.data && (
        <div className="bg-dark-900 rounded-lg border border-dark-700 p-4 space-y-2">
          <h2 className="text-sm font-medium text-muted-200">Latest Evaluation</h2>
          <p className="text-sm text-muted-300">
            {evaluateMutation.data.alert_count} active alert
            {evaluateMutation.data.alert_count === 1 ? '' : 's'} detected.
          </p>
          {(evaluateMutation.data.notifications_queued > 0 ||
            evaluateMutation.data.notifications_sent > 0 ||
            evaluateMutation.data.notifications_failed > 0) && (
            <p className="text-xs text-muted-400">
              Notifications: {evaluateMutation.data.notifications_queued} queued,{' '}
              {evaluateMutation.data.notifications_sent} sent,{' '}
              {evaluateMutation.data.notifications_failed} failed.
            </p>
          )}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
            {evaluateMutation.data.window_metrics.map((windowMetric) => (
              <div key={windowMetric.window_days} className="bg-dark-800 rounded-lg p-3">
                <p className="text-xs text-muted-400">Window: {windowMetric.window_days}d</p>
                <p className="text-xs text-muted-300 mt-1">
                  {windowMetric.trace_count} traces · {windowMetric.error_rate_percent.toFixed(1)}% errors
                </p>
                <p className="text-xs text-muted-500 mt-1">
                  Avg duration {windowMetric.avg_duration_ms.toFixed(1)}ms
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="bg-dark-900 rounded-lg border border-dark-700">
        <div className="px-4 py-3 border-b border-dark-700 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <h2 className="text-sm font-medium text-muted-200">Recent Alert Events</h2>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={eventTypeFilter}
              onChange={(event) => setEventTypeFilter(event.target.value as AlertEventType | 'all')}
              aria-label="Event type filter"
              className="rounded-lg border border-dark-700 bg-dark-800 px-3 py-2 text-xs text-muted-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
            >
              <option value="all">All event types</option>
              {EVENT_TYPE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <select
              value={eventRuleFilter}
              onChange={(event) => setEventRuleFilter(event.target.value)}
              aria-label="Event rule filter"
              className="rounded-lg border border-dark-700 bg-dark-800 px-3 py-2 text-xs text-muted-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
            >
              <option value="all">All rules</option>
              {rules.map((rule) => (
                <option key={rule.id} value={rule.id}>
                  {rule.name}
                </option>
              ))}
            </select>
            <button
              type="button"
              aria-label="Previous events page"
              onClick={() => setEventOffset((current) => Math.max(0, current - EVENTS_PAGE_SIZE))}
              disabled={eventOffset === 0 || eventsQuery.isFetching}
              className={clsx(
                'rounded-lg border px-3 py-2 text-xs transition-colors',
                eventOffset === 0 || eventsQuery.isFetching
                  ? 'border-dark-700 text-muted-500 cursor-not-allowed'
                  : 'border-dark-700 bg-dark-800 text-muted-100 hover:bg-dark-700'
              )}
            >
              Prev
            </button>
            <button
              type="button"
              aria-label="Next events page"
              onClick={() => setEventOffset((current) => current + EVENTS_PAGE_SIZE)}
              disabled={!hasNextEventsPage || eventsQuery.isFetching}
              className={clsx(
                'rounded-lg border px-3 py-2 text-xs transition-colors',
                !hasNextEventsPage || eventsQuery.isFetching
                  ? 'border-dark-700 text-muted-500 cursor-not-allowed'
                  : 'border-dark-700 bg-dark-800 text-muted-100 hover:bg-dark-700'
              )}
            >
              Next
            </button>
            <span className="text-xs text-muted-500">Page {Math.floor(eventOffset / EVENTS_PAGE_SIZE) + 1}</span>
          </div>
        </div>
        {eventsQuery.isLoading ? (
          <div className="flex items-center justify-center h-20">
            <Loader2 className="h-5 w-5 text-primary-500 animate-spin" />
          </div>
        ) : eventsQuery.error ? (
          <div className="p-4 text-sm text-red-400">Failed to load alert events.</div>
        ) : events.length === 0 ? (
          <div className="p-4 text-sm text-muted-400">No alert events yet.</div>
        ) : (
          <div className="divide-y divide-dark-700">
            {events.map((event) => (
              <div key={event.id} className="px-4 py-3 flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm text-muted-100">{formatEventType(event.event_type)}</p>
                  <p className="text-xs text-muted-400 mt-1">
                    {event.rule_name ?? 'Unknown rule'}
                    {event.current_value !== null && event.threshold !== null
                      ? ` · current ${event.current_value.toFixed(2)} vs ${event.threshold.toFixed(2)}`
                      : ''}
                  </p>
                  {event.message && <p className="text-xs text-muted-500 mt-1">{event.message}</p>}
                </div>
                <p className="text-xs text-muted-500 whitespace-nowrap">
                  {new Date(event.created_at).toLocaleString()}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="bg-dark-900 rounded-lg border border-dark-700">
        <div className="px-4 py-3 border-b border-dark-700">
          <h2 className="text-sm font-medium text-muted-200">Dead-Letter Notifications</h2>
        </div>
        {deadLettersQuery.isLoading ? (
          <div className="flex items-center justify-center h-20">
            <Loader2 className="h-5 w-5 text-primary-500 animate-spin" />
          </div>
        ) : deadLettersQuery.error ? (
          <div className="p-4 text-sm text-red-400">Failed to load dead-letter alerts.</div>
        ) : deadLetters.length === 0 ? (
          <div className="p-4 text-sm text-muted-400">No failed notifications to replay.</div>
        ) : (
          <div className="divide-y divide-dark-700">
            {deadLetters.map((deadLetter) => (
              <div key={deadLetter.id} className="px-4 py-3 flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm text-muted-100">
                    {deadLetter.rule_name ?? 'Unknown rule'} → {deadLetter.destination_name ?? 'Unknown destination'}
                  </p>
                  <p className="text-xs text-muted-400 mt-1">
                    {formatEventType(deadLetter.event_type)}
                    {deadLetter.current_value !== null ? ` · current ${deadLetter.current_value.toFixed(2)}` : ''}
                  </p>
                  {deadLetter.message && (
                    <p className="text-xs text-muted-500 mt-1">{deadLetter.message}</p>
                  )}
                  <p className="text-xs text-muted-500 mt-1">
                    Attempts: {deadLetter.replay_attempts} · Remaining: {deadLetter.replay_attempts_remaining}
                  </p>
                  {deadLetter.replay_blocked_reason && (
                    <p className="text-xs text-amber-400 mt-1">{deadLetter.replay_blocked_reason}</p>
                  )}
                  <p className="text-xs text-muted-500 mt-1">
                    {new Date(deadLetter.created_at).toLocaleString()}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => replayDeadLetterMutation.mutate(deadLetter.id)}
                  disabled={
                    replayDeadLetterMutation.isPending || !deadLetter.replayable
                  }
                  className={clsx(
                    'inline-flex items-center gap-1 px-2.5 py-1 text-xs rounded border transition-colors',
                    replayDeadLetterMutation.isPending || !deadLetter.replayable
                      ? 'border-dark-700 text-muted-500 cursor-not-allowed'
                      : 'border-primary-700 text-primary-300 hover:bg-primary-900/20'
                  )}
                >
                  <Webhook className="h-3 w-3" />
                  Replay
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="bg-dark-900 rounded-lg border border-dark-700">
        <div className="px-4 py-3 border-b border-dark-700">
          <h2 className="text-sm font-medium text-muted-200">Configured Rules</h2>
        </div>
        {rulesQuery.isLoading ? (
          <div className="flex items-center justify-center h-32">
            <Loader2 className="h-6 w-6 text-primary-500 animate-spin" />
          </div>
        ) : rulesQuery.error ? (
          <div className="p-4 text-sm text-red-400">Failed to load alert rules.</div>
        ) : rules.length === 0 ? (
          <div className="p-4 text-sm text-muted-400">No alert rules yet.</div>
        ) : (
          <div className="divide-y divide-dark-700">
            {rules.map((rule) => {
              const evaluated = evaluatedById.get(rule.id)
              const breached = evaluated?.breached ?? false
              const currentValue = evaluated?.current_value

              return (
                <div key={rule.id} className="px-4 py-3 flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm text-muted-100">{rule.name}</p>
                    <p className="text-xs text-muted-400 mt-1">
                      {formatMetric(rule.metric)} {rule.operator} {rule.threshold} · {rule.window_days}d window
                    </p>
                    <p className="text-xs text-muted-500 mt-1">
                      Cooldown: {rule.notification_cooldown_minutes}m · Last triggered:{' '}
                      {rule.last_triggered_at ? new Date(rule.last_triggered_at).toLocaleString() : 'never'}
                    </p>
                    <p className="text-xs text-muted-500 mt-1">
                      Last notified:{' '}
                      {rule.last_notified_at ? new Date(rule.last_notified_at).toLocaleString() : 'never'}
                    </p>
                  </div>

                  <div className="flex items-center gap-2">
                    {currentValue !== undefined && (
                      <span
                        className={clsx(
                          'inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs border',
                          breached
                            ? 'bg-red-900/30 border-red-700 text-red-300'
                            : 'bg-dark-800 border-dark-700 text-muted-300'
                        )}
                      >
                        {breached && <AlertTriangle className="h-3 w-3" />}
                        Current: {currentValue.toFixed(2)}
                      </span>
                    )}
                    <button
                      type="button"
                      onClick={() =>
                        toggleMutation.mutate({
                          ruleId: rule.id,
                          isActive: !rule.is_active,
                        })
                      }
                      disabled={toggleMutation.isPending}
                      className={clsx(
                        'px-2.5 py-1 text-xs rounded border',
                        rule.is_active
                          ? 'border-emerald-700 text-emerald-300 hover:bg-emerald-900/20'
                          : 'border-amber-700 text-amber-300 hover:bg-amber-900/20'
                      )}
                    >
                      {rule.is_active ? 'Active' : 'Paused'}
                    </button>
                    <button
                      type="button"
                      onClick={() => deleteMutation.mutate(rule.id)}
                      disabled={deleteMutation.isPending}
                      className="inline-flex items-center gap-1 px-2.5 py-1 text-xs rounded border border-red-700 text-red-300 hover:bg-red-900/20"
                    >
                      <Trash2 className="h-3 w-3" />
                      Delete
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
