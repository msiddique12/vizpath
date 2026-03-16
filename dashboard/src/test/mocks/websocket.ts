type MessageHandler = (event: MessageEvent) => void
type CloseHandler = (event: CloseEvent) => void

export class MockWebSocket {
  static instances: MockWebSocket[] = []

  static CONNECTING = 0
  static OPEN = 1
  static CLOSING = 2
  static CLOSED = 3

  static reset(): void {
    MockWebSocket.instances = []
  }

  static latest(): MockWebSocket {
    return MockWebSocket.instances[MockWebSocket.instances.length - 1] as MockWebSocket
  }

  readonly url: string
  readyState = MockWebSocket.CONNECTING
  onopen: (() => void) | null = null
  onmessage: MessageHandler | null = null
  onclose: CloseHandler | null = null
  onerror: (() => void) | null = null
  public readonly sentMessages: string[] = []

  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
    queueMicrotask(() => {
      if (this.onopen) {
        this.readyState = MockWebSocket.OPEN
        this.onopen()
      }
    })
  }

  send(message: string): void {
    this.sentMessages.push(message)
  }

  close(code = 1000, reason = ''): void {
    this.readyState = MockWebSocket.CLOSED
    if (this.onclose) {
      const event = {
        code,
        reason,
        wasClean: code === 1000,
      } as CloseEvent
      this.onclose(event)
    }
  }

  triggerMessage(data: string): void {
    if (!this.onmessage) {
      return
    }
    this.onmessage(new MessageEvent('message', { data }))
  }

  triggerError(): void {
    if (this.onerror) {
      this.onerror()
    }
  }

  triggerClose(code = 1000, reason = ''): void {
    this.close(code, reason)
  }
}
