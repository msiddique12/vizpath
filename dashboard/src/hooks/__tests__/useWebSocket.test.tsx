import { act, render } from '@testing-library/react'
import { useCallback } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { waitFor } from '@testing-library/react'
import { useWebSocket } from '../useWebSocket'
import { MockWebSocket } from '../../test/mocks/websocket'

interface CloseReason {
  code: number
  reason: string
  canRetry: boolean
}

interface HarnessState {
  state: { connected: boolean; lastDisconnect: CloseReason | null }
  reconnect: () => void
}

function createHarness(onDisconnect: (event: CloseReason | null) => void) {
  const stateHolder: HarnessState = {
    state: { connected: false, lastDisconnect: null },
    reconnect: () => {},
  }

  const Harness = () => {
    const onConnect = useCallback(() => {
      stateHolder.state = { ...stateHolder.state, connected: true }
    }, [])

    const onMessage = useCallback(() => {
      // no assertions from hook-level message callback in this harness
    }, [])

    const handleDisconnect = (event: CloseReason | null) => {
      stateHolder.state = {
        ...stateHolder.state,
        connected: false,
        lastDisconnect: event,
      }
      onDisconnect(event)
    }

    const ws = useWebSocket({
      onMessage,
      onDisconnect: handleDisconnect,
      onConnect,
    })

    stateHolder.state = { ...stateHolder.state, connected: ws.connected, lastDisconnect: ws.lastDisconnect }
    stateHolder.reconnect = ws.reconnect

    return null
  }

  return {
    renderResult: render(<Harness />),
    stateHolder,
  }
}

describe('useWebSocket', () => {
  let originalWebSocket: typeof WebSocket

  beforeEach(() => {
    originalWebSocket = globalThis.WebSocket
    globalThis.WebSocket = MockWebSocket as typeof WebSocket
    MockWebSocket.reset()
  })

  afterEach(() => {
    if (vi.isFakeTimers()) {
      vi.useRealTimers()
    }
    globalThis.WebSocket = originalWebSocket
  })

  it('does not automatically reconnect after unauthorized close', async () => {
    const onDisconnect = vi.fn()
    const { stateHolder, renderResult } = createHarness(onDisconnect)

    await waitFor(() => {
      expect(MockWebSocket.instances).toHaveLength(1)
      expect(stateHolder.state.connected).toBe(true)
    })

    act(() => {
      MockWebSocket.latest().triggerClose(4001, 'Unauthorized')
    })

    expect(stateHolder.state.lastDisconnect).toEqual({
      code: 4001,
      reason: 'Unauthorized',
      canRetry: false,
    })
    expect(stateHolder.state.connected).toBe(false)
    expect(onDisconnect).toHaveBeenCalledWith({
      code: 4001,
      reason: 'Unauthorized',
      canRetry: false,
    })

    act(() => {
      vi.useFakeTimers()
      vi.advanceTimersByTime(35_000)
    })
    expect(stateHolder.state.lastDisconnect?.canRetry).toBe(false)
    expect(MockWebSocket.instances).toHaveLength(1)

    renderResult.unmount()
  })

  it('reconnects automatically for retryable close codes', async () => {
    const onDisconnect = vi.fn()
    const { stateHolder, renderResult } = createHarness(onDisconnect)
    const timeoutSpy = vi.spyOn(globalThis, 'setTimeout')

    await waitFor(() => {
      expect(stateHolder.state.connected).toBe(true)
      expect(MockWebSocket.instances).toHaveLength(1)
    })
    timeoutSpy.mockClear()

    act(() => {
      MockWebSocket.latest().triggerClose(1000, 'Normal close')
    })

    expect(onDisconnect).toHaveBeenCalledOnce()
    expect(stateHolder.state.lastDisconnect?.canRetry).toBe(true)
    expect(stateHolder.state.connected).toBe(false)

    expect(timeoutSpy).toHaveBeenCalledWith(expect.any(Function), 2000)
    const reconnectDelayScheduled = timeoutSpy.mock.calls.some(([, delay]) => delay === 2000)
    expect(reconnectDelayScheduled).toBe(true)

    expect(stateHolder.state.lastDisconnect?.canRetry).toBe(true)
    timeoutSpy.mockRestore()
    renderResult.unmount()
  })

  it('replies pong to ping messages and keeps connection open', async () => {
    const onDisconnect = vi.fn()
    const { stateHolder } = createHarness(onDisconnect)

    await waitFor(() => {
      expect(stateHolder.state.connected).toBe(true)
      expect(MockWebSocket.instances).toHaveLength(1)
    })

    const socket = MockWebSocket.latest()
    act(() => {
      socket.triggerMessage('{"type":"ping"}')
    })

    expect(socket.sentMessages).toEqual(['pong'])
    expect(stateHolder.state.connected).toBe(true)
  })
}
)
