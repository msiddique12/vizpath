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

interface UseWebSocketOptions {
  onMessage?: (message: WebSocketMessage) => void
  onConnect?: () => void
  onDisconnect?: (event: CloseReason | null) => void
}

export function useWebSocket(options: UseWebSocketOptions = {}) {
  const { onMessage, onConnect, onDisconnect } = options
  const wsRef = useRef<WebSocket | null>(null)
  const [connected, setConnected] = useState(false)
  const [lastDisconnect, setLastDisconnect] = useState<CloseReason | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout>>()
  const reconnectAttemptRef = useRef(0)
  const shouldReconnectRef = useRef(true)
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
    const baseUrl = configuredBase?.trim()
      ? configuredBase.trim()
      : window.location.origin.replace(/^http/, 'ws')
    const url = new URL('/ws/traces', baseUrl.endsWith('/') ? baseUrl : `${baseUrl}/`)

    const apiKey = configuredApiKey?.trim()
    if (apiKey) {
      url.searchParams.set('api_key', apiKey)
    }

    return url.toString()
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

  useEffect(() => {
    connect()

    return () => {
      resetConnection()
    }
  }, [connect, resetConnection])

  return { connected, lastDisconnect, reconnect }
}
