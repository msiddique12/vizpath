import { useCallback, useEffect, useRef, useState } from 'react'

interface WebSocketMessage {
  type: string
  trace_id?: string
  span_count?: number
}

type CloseReason = {
  code: number
  reason: string
  canRetry: boolean
}

const AUTH_FAILURE_CODE = 4001
const AUTH_FAILURE_REASON = 'Authentication required to stream live updates.'
const WEBSOCKET_PATH = '/ws/traces'

type WebSocketUrlOptions = {
  configuredBaseUrl: string | undefined
  configuredApiKey: string | undefined
  runtimeApiKey: string
  origin: string
}

const normalizeWebSocketBase = (rawBase: string) => {
  if (/^https?:\/\//i.test(rawBase)) {
    return rawBase.replace(/^https?:\/\//i, (match) => (match === 'https://' ? 'wss://' : 'ws://'))
  }
  return rawBase
}

const buildWebSocketUrl = ({
  configuredBaseUrl,
  configuredApiKey,
  runtimeApiKey,
  origin,
}: WebSocketUrlOptions): string => {
  const fallbackBase = normalizeWebSocketBase(origin.replace(/^https?:/i, (match) => (match === 'https:' ? 'wss:' : 'ws:')))
  const candidateBase = configuredBaseUrl?.trim()
    ? configuredBaseUrl.trim()
    : fallbackBase
  const normalizedBase = normalizeWebSocketBase(candidateBase).replace(/\/$/, '')
  const apiKey = runtimeApiKey || configuredApiKey?.trim()
  const build = (base: string) => {
    const url = new URL(WEBSOCKET_PATH, `${base}/`)
    if (apiKey) {
      url.searchParams.set('api_key', apiKey)
    }
    return url.toString()
  }

  try {
    return build(normalizedBase)
  } catch {
    return build(fallbackBase)
  }
}

interface UseWebSocketOptions {
  onMessage?: (message: WebSocketMessage) => void
  onConnect?: () => void
  onDisconnect?: (event: CloseReason | null) => void
  apiKey?: string
}

export function useWebSocket(options: UseWebSocketOptions = {}) {
  const { onMessage, onConnect, onDisconnect, apiKey } = options
  const wsRef = useRef<WebSocket | null>(null)
  const [connected, setConnected] = useState(false)
  const [lastDisconnect, setLastDisconnect] = useState<CloseReason | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout>>()
  const reconnectAttemptRef = useRef(0)
  const shouldReconnectRef = useRef(true)
  const apiKeyRef = useRef<string>(apiKey?.trim() || '')
  const onMessageRef = useRef<(message: WebSocketMessage) => void>()
  const onConnectRef = useRef<(() => void) | undefined>()
  const onDisconnectRef = useRef<((event: CloseReason | null) => void) | undefined>()

  useEffect(() => {
    onMessageRef.current = onMessage
    onConnectRef.current = onConnect
    onDisconnectRef.current = onDisconnect
  }, [onConnect, onDisconnect, onMessage])

  const resolveWebSocketUrl = () => {
    const configuredBase = import.meta.env.VITE_WS_BASE_URL as string | undefined
    const configuredApiKey = import.meta.env.VITE_VIZPATH_API_KEY as string | undefined
    const runtimeApiKey = apiKeyRef.current?.trim()

    return buildWebSocketUrl({
      configuredBaseUrl: configuredBase,
      configuredApiKey,
      runtimeApiKey,
      origin: window.location.origin,
    })
  }

  const connect = useCallback(() => {
    shouldReconnectRef.current = true
    if (
      wsRef.current?.readyState === WebSocket.OPEN ||
      wsRef.current?.readyState === WebSocket.CONNECTING
    ) {
      return
    }

    const url = resolveWebSocketUrl()

    try {
      const ws = new WebSocket(url)

      ws.onopen = () => {
        reconnectAttemptRef.current = 0
        setConnected(true)
        setLastDisconnect(null)
        onConnectRef.current?.()
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'ping') {
            ws.send('pong')
            return
          }
          onMessageRef.current?.(data)
        } catch {
          // Ignore non-JSON messages
        }
      }

      ws.onclose = (event) => {
        wsRef.current = null
        setConnected(false)
        const isAuthFailure = event.code === AUTH_FAILURE_CODE
        const rawReason = event.reason?.trim()
        const reason: CloseReason = {
          code: event.code,
          reason: rawReason || (isAuthFailure ? AUTH_FAILURE_REASON : 'Disconnected'),
          canRetry: !isAuthFailure,
        }
        setLastDisconnect(reason)
        onDisconnectRef.current?.(reason)

        if (!shouldReconnectRef.current) {
          return
        }

        if (isAuthFailure) {
          return
        }

        if (reconnectAttemptRef.current >= 0) {
          reconnectAttemptRef.current += 1
          const delay = Math.min(1000 * 2 ** Math.min(reconnectAttemptRef.current, 5), 30_000)
          reconnectTimeoutRef.current = setTimeout(() => {
            connect()
          }, delay)
        }
      }

      ws.onerror = () => {
        ws.close()
      }

      wsRef.current = ws
    } catch {
      reconnectTimeoutRef.current = setTimeout(connect, 3000)
    }
  }, [])

  useEffect(() => {
    apiKeyRef.current = apiKey?.trim() || ''
  }, [apiKey])

  const resetConnection = useCallback(() => {
    shouldReconnectRef.current = false
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = undefined
    }

    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
  }, [])

  const reconnect = useCallback(() => {
    shouldReconnectRef.current = true
    connect()
  }, [connect])

  const setApiKey = useCallback(
    (nextApiKey: string) => {
      apiKeyRef.current = nextApiKey.trim()
      resetConnection()
      reconnect()
    },
    [reconnect, resetConnection]
  )

  useEffect(() => {
    connect()

    return () => {
      resetConnection()
    }
  }, [connect, resetConnection])

  return { connected, lastDisconnect, reconnect, setApiKey }
}

export { buildWebSocketUrl }
