import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { CheckCircle2, Circle, Copy, ExternalLink, Loader2, PlayCircle, Server, Sparkles, Wifi, WifiOff } from 'lucide-react'
import {
  getDemoPreflight,
  getDetailedHealth,
  getIntelligenceStatus,
  getLatestStoryMode,
  seedStoryMode,
  type DemoPreflightResponse,
} from '@/lib/api'
import { useWebSocket } from '@/hooks/useWebSocket'
import WebSocketRecoveryPanel from '@/components/WebSocketRecoveryPanel'

function StatusDot({ ok }: { ok: boolean }) {
  return ok ? (
    <CheckCircle2 className="h-4 w-4 text-green-400" />
  ) : (
    <Circle className="h-4 w-4 text-muted-500" />
  )
}

export default function DemoPage() {
  const [copiedCmd, setCopiedCmd] = useState<string | null>(null)
  const [lastWsEvent, setLastWsEvent] = useState<string | null>(null)
  const [lastWsTimestamp, setLastWsTimestamp] = useState<string | null>(null)

  const healthQuery = useQuery({
    queryKey: ['health-detailed'],
    queryFn: getDetailedHealth,
    refetchInterval: 5000,
  })

  const preflightQuery = useQuery({
    queryKey: ['demo-preflight'],
    queryFn: getDemoPreflight,
    refetchInterval: 5000,
  })

  const intelligenceQuery = useQuery({
    queryKey: ['intelligence-status'],
    queryFn: getIntelligenceStatus,
    refetchInterval: 5000,
  })

  const { connected: websocketConnected, lastDisconnect, reconnect, setApiKey: setRuntimeWebSocketKey } =
    useWebSocket({
    onConnect: () => {
      setLastWsEvent('WebSocket connected to trace stream')
      setLastWsTimestamp(new Date().toLocaleTimeString())
    },
    onDisconnect: (event) => {
      if (event?.reason) {
        setLastWsEvent(`WebSocket disconnected: ${event.reason}`)
      } else {
        setLastWsEvent('WebSocket disconnected from trace stream')
      }
      setLastWsTimestamp(new Date().toLocaleTimeString())
    },
    onMessage: (message) => {
      const traceId = message.trace_id ? `Trace ${message.trace_id}` : 'Trace stream'
      const spanCount =
        message.span_count !== undefined ? ` (${message.span_count} spans)` : ''
      setLastWsEvent(`Received ${message.type} for ${traceId}${spanCount}`)
      setLastWsTimestamp(new Date().toLocaleTimeString())
    },
  })


  const latestStoryModeQuery = useQuery({
    queryKey: ['latest-story-mode'],
    queryFn: getLatestStoryMode,
    refetchInterval: 5000,
  })

  const isLoading =
    healthQuery.isLoading || intelligenceQuery.isLoading || preflightQuery.isLoading
  const dbReady = healthQuery.data?.checks.database?.status === 'healthy'
  const redisReady = healthQuery.data?.checks.redis?.status === 'healthy'
  const apiReady = healthQuery.data?.status === 'healthy' || healthQuery.data?.status === 'degraded'
  const nimReady = intelligenceQuery.data?.nvidia_api_key_configured ?? false
  const isAuthFailure = lastDisconnect?.code === 4001
  const authKeyConfigured = Boolean(import.meta.env.VITE_VIZPATH_API_KEY?.trim())
  const preflightData: DemoPreflightResponse | undefined = preflightQuery.data
  const canSeedStory = preflightData?.can_seed ?? false
  const demoBlockers = preflightData?.blockers ?? []
  const demoRecommendations = preflightData?.recommendations ?? []
  const demoFixCommands = preflightData?.fix_commands ?? []
  const latestStoryMode = latestStoryModeQuery.data

  const runCommand = 'python -m examples.code_agent.run "How does the intelligence module work?" -v'
  const startupCommand = './demo.sh'

  const storyModeMutation = useMutation({
    mutationFn: () => seedStoryMode('agent_regression'),
  })

  const copyText = async (text: string, key: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedCmd(key)
      setTimeout(() => setCopiedCmd(null), 1500)
    } catch {
      setCopiedCmd(null)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-muted-100">Demo Mode</h1>
        <p className="mt-1 text-sm text-muted-400">
          Run a complete end-to-end demo with live trace visualization and intelligence checks.
        </p>
      </div>

      <div className="bg-dark-900 rounded-lg border border-dark-700 p-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-muted-200 flex items-center gap-2">
            <Server className="h-4 w-4" />
            Readiness Status
          </h2>
          {isLoading && <Loader2 className="h-4 w-4 animate-spin text-muted-400" />}
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-4">
          <div className="bg-dark-800 rounded-lg p-3 flex items-center justify-between">
            <span className="text-sm text-muted-300">API reachable</span>
            <StatusDot ok={!!apiReady} />
          </div>
          <div className="bg-dark-800 rounded-lg p-3 flex items-center justify-between">
            <span className="text-sm text-muted-300">Database healthy</span>
            <StatusDot ok={!!dbReady} />
          </div>
          <div className="bg-dark-800 rounded-lg p-3 flex items-center justify-between">
            <span className="text-sm text-muted-300">Redis healthy</span>
            <StatusDot ok={!!redisReady} />
          </div>
          <div className="bg-dark-800 rounded-lg p-3 flex items-center justify-between">
            <span className="text-sm text-muted-300">NVIDIA key configured</span>
            <StatusDot ok={nimReady} />
          </div>
        </div>

        {demoFixCommands.length > 0 && (
          <div className="mt-3 text-xs text-muted-300">
            <div className="mb-1 text-muted-200">Suggested setup commands:</div>
            <div className="space-y-2">
              {demoFixCommands.map((command, index) => (
                <div
                  key={`${command}-${index}`}
                  className="bg-dark-800 rounded-lg p-2 flex items-center justify-between gap-2"
                >
                  <code className="text-muted-200 text-[11px] break-all">{command}</code>
                  <button
                    onClick={() => copyText(command, `fix-${index}`)}
                    className="inline-flex items-center gap-1 text-xs text-muted-300 hover:text-muted-100 shrink-0"
                  >
                    <Copy className="h-3 w-3" />
                    {copiedCmd === `fix-${index}` ? 'Copied' : 'Copy'}
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {(healthQuery.isError || intelligenceQuery.isError || latestStoryModeQuery.isError) && (
          <div className="mt-3 text-xs text-red-400">
            Could not fetch readiness data. Make sure `./demo.sh` is running.
          </div>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span
            className={clsx(
              'inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs',
              websocketConnected
                ? 'bg-green-900/30 text-green-400'
                : isAuthFailure
                  ? 'bg-amber-900/30 text-amber-300'
                : 'bg-dark-700 text-muted-400'
            )}
          >
            {websocketConnected ? <Wifi className="h-3 w-3" /> : <WifiOff className="h-3 w-3" />}
            {websocketConnected
              ? 'Trace stream live'
              : isAuthFailure
                ? 'Trace stream auth required'
                : 'Trace stream reconnecting'}
          </span>

          {(lastWsEvent || lastWsTimestamp) && (
            <span className="inline-flex items-center gap-1 rounded-full bg-dark-800 px-3 py-1 text-xs text-muted-200">
              {lastWsEvent && <span>{lastWsEvent}</span>}
              {lastWsTimestamp && <span className="text-muted-500">· {lastWsTimestamp}</span>}
            </span>
          )}
        </div>
        <WebSocketRecoveryPanel
          isConnected={websocketConnected}
          lastDisconnect={lastDisconnect}
          authKeyConfigured={authKeyConfigured}
          onRetry={reconnect}
          onSubmitApiKey={setRuntimeWebSocketKey}
          inputId="demo-ws-auth-key-input"
        />
      </div>

      <div className="bg-dark-900 rounded-lg border border-dark-700 p-4">
        <h2 className="text-sm font-medium text-muted-200 flex items-center gap-2">
          <PlayCircle className="h-4 w-4" />
          Demo Checklist
        </h2>
        <div className="mt-3 mb-3">
          <button
            onClick={async () => {
              const data = await storyModeMutation.mutateAsync()
              window.location.href = data.recommended_flow.compare
            }}
            disabled={storyModeMutation.isPending || !canSeedStory}
            className={clsx(
              'inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm border',
              storyModeMutation.isPending || !canSeedStory
                ? 'bg-dark-800 border-dark-700 text-muted-500 cursor-not-allowed'
                : 'bg-primary-900/30 border-primary-800 text-primary-300 hover:bg-primary-900/45'
            )}
          >
            {storyModeMutation.isPending || !canSeedStory ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Sparkles className="h-4 w-4" />
            )}
            {!canSeedStory ? 'Waiting for database readiness' : 'Start Story Mode (seed + open compare)'}
          </button>
          {storyModeMutation.isError && (
            <p className="text-xs text-red-400 mt-2">
              Failed to seed story mode data. Confirm the API is running.
            </p>
          )}
          {demoBlockers.length > 0 && (
            <div className="mt-2 text-xs text-red-400">
              {demoBlockers.map((item, index) => (
                <div key={`${item}-${index}`}>• {item}</div>
              ))}
            </div>
          )}
          {demoRecommendations.length > 0 && demoBlockers.length === 0 && (
            <div className="mt-2 text-xs text-amber-400">
              {demoRecommendations.map((item, index) => (
                <div key={`${item}-${index}`}>• {item}</div>
              ))}
            </div>
          )}
          {storyModeMutation.data && (
            <p className="text-xs text-green-400 mt-2">
              Seeded {storyModeMutation.data.seeded} traces for scenario{' '}
              <span className="text-muted-100">{storyModeMutation.data.scenario}</span>.
            </p>
          )}

          {latestStoryMode?.found && (
            <p className="text-xs text-muted-300 mt-2">
              Resume existing story-mode scenario: <span className="text-muted-100">{latestStoryMode.scenario}</span>.
            </p>
          )}
        </div>

        {latestStoryMode?.found && (
          <button
            onClick={() => {
              window.location.href = latestStoryMode.recommended_flow.compare
            }}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm border bg-dark-800 border-dark-700 text-muted-300 hover:bg-dark-700"
          >
            Open Latest Story-Mode Run
          </button>
        )}
        <ol className="mt-3 space-y-3 text-sm text-muted-300">
          <li className="bg-dark-800 rounded-lg p-3">
            In terminal 1, run the stack startup script.
            <div className="mt-2 flex items-center gap-2">
              <code className="text-xs text-muted-200 bg-dark-900 border border-dark-700 rounded px-2 py-1">
                {startupCommand}
              </code>
              <button
                onClick={() => copyText(startupCommand, 'startup')}
                className="inline-flex items-center gap-1 text-xs text-muted-300 hover:text-muted-100"
              >
                <Copy className="h-3 w-3" />
                {copiedCmd === 'startup' ? 'Copied' : 'Copy'}
              </button>
            </div>
          </li>

          <li className="bg-dark-800 rounded-lg p-3">
            In terminal 2, run the demo agent.
            <div className="mt-2 flex items-center gap-2">
              <code className="text-xs text-muted-200 bg-dark-900 border border-dark-700 rounded px-2 py-1 break-all">
                {runCommand}
              </code>
              <button
                onClick={() => copyText(runCommand, 'agent')}
                className="inline-flex items-center gap-1 text-xs text-muted-300 hover:text-muted-100"
              >
                <Copy className="h-3 w-3" />
                {copiedCmd === 'agent' ? 'Copied' : 'Copy'}
              </button>
            </div>
          </li>

          <li className="bg-dark-800 rounded-lg p-3">
            Open the latest trace and show timeline, DAG, and heatmap views.
          </li>

          <li className="bg-dark-800 rounded-lg p-3">
            Run <span className="text-muted-100">Analyze</span> and{' '}
            <span className="text-muted-100">Deep Analysis</span> in the trace detail panel.
          </li>

          <li className="bg-dark-800 rounded-lg p-3">
            Add curation labels, then export synthetic data from the Curation page.
          </li>
        </ol>
      </div>

      <div className="bg-dark-900 rounded-lg border border-dark-700 p-4">
        <h2 className="text-sm font-medium text-muted-200 flex items-center gap-2">
          <Sparkles className="h-4 w-4" />
          Quick Links
        </h2>
        <div className="mt-3 flex flex-wrap gap-2">
          <a
            href="/traces"
            className={clsx(
              'inline-flex items-center gap-1 px-3 py-2 rounded-lg text-sm',
              'bg-dark-800 text-muted-200 hover:bg-dark-700'
            )}
          >
            Traces <ExternalLink className="h-3 w-3" />
          </a>
          <a
            href="/curation"
            className={clsx(
              'inline-flex items-center gap-1 px-3 py-2 rounded-lg text-sm',
              'bg-dark-800 text-muted-200 hover:bg-dark-700'
            )}
          >
            Curation <ExternalLink className="h-3 w-3" />
          </a>
          <a
            href="http://localhost:8000/docs"
            target="_blank"
            rel="noreferrer"
            className={clsx(
              'inline-flex items-center gap-1 px-3 py-2 rounded-lg text-sm',
              'bg-dark-800 text-muted-200 hover:bg-dark-700'
            )}
          >
            API Docs <ExternalLink className="h-3 w-3" />
          </a>
        </div>
      </div>
    </div>
  )
}
