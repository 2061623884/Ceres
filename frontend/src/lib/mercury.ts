/**
 * Mercury customer service API client
 * Mirrors the pattern from saleGuide.ts
 */

import type { Order } from './saleGuide'

export interface MercurySessionResponse {
  session_id: string
  created_at: string
  selected_order_id: string | null
}

export interface MercuryOrderResponse {
  session_id: string
  order: Order
}

export interface MercuryTurnCallbacks {
  onAnswerDelta?: (text: string) => void
  onOrders?: (orders: Order[]) => void
  onCompleted?: (finalText: string) => void
  onError?: (error: string) => void
}

function normalizeSseNewlines(buffer: string): string {
  return buffer.replace(/\r\n/g, '\n').replace(/\r/g, '\n')
}

function dispatchSseBlock(block: string, callbacks: MercuryTurnCallbacks): void {
  const trimmed = block.trim()
  if (!trimmed) return

  let eventName = ''
  let dataPayload = ''

  for (const line of trimmed.split('\n')) {
    if (line.startsWith('event:')) {
      eventName = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      dataPayload = line.slice(5).trim()
    }
  }

  if (!eventName || !dataPayload) return

  try {
    const data = JSON.parse(dataPayload) as Record<string, unknown>
    switch (eventName) {
      case 'answer.delta':
        if (typeof data.text === 'string') {
          callbacks.onAnswerDelta?.(data.text)
        }
        break
      case 'orders':
        callbacks.onOrders?.(data.items as Order[])
        break
      case 'turn.completed':
        if (typeof data.final_text === 'string') {
          callbacks.onCompleted?.(data.final_text)
        }
        break
      case 'error':
        callbacks.onError?.(
          typeof data.message === 'string' ? data.message : '服务暂时不可用',
        )
        break
    }
  } catch {
    callbacks.onError?.('回复解析失败')
  }
}

function consumeSseBuffer(
  buffer: string,
  callbacks: MercuryTurnCallbacks,
): string {
  const normalized = normalizeSseNewlines(buffer)
  const parts = normalized.split('\n\n')
  const remainder = parts.pop() ?? ''
  for (const part of parts) {
    dispatchSseBlock(part, callbacks)
  }
  return remainder
}

/**
 * Create a new Mercury session
 */
export async function createMercurySession(): Promise<string> {
  const resp = await fetch('/api/v1/mercury/sessions', {
    method: 'POST',
    credentials: 'include',
  })

  if (!resp.ok) {
    throw new Error(`Failed to create session: ${resp.statusText}`)
  }

  const data: MercurySessionResponse = await resp.json()
  return data.session_id
}

export async function selectMercuryOrder(
  sessionId: string,
  orderId: string,
): Promise<MercuryOrderResponse> {
  const resp = await fetch(`/api/v1/mercury/sessions/${encodeURIComponent(sessionId)}/order`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ order_id: orderId }),
  })

  if (!resp.ok) {
    throw new Error(`Failed to select order: ${resp.statusText}`)
  }

  return resp.json()
}

/**
 * Send a message to Mercury and receive streaming response
 */
export async function sendMercuryTurn(
  sessionId: string,
  message: string,
  callbacks: MercuryTurnCallbacks = {},
): Promise<void> {
  const requestId = `req_${Date.now()}`

  const resp = await fetch(`/api/v1/mercury/sessions/${sessionId}/turns/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ message, request_id: requestId }),
  })

  if (!resp.ok) {
    throw new Error(`Failed to send message: ${resp.statusText}`)
  }

  const reader = resp.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let assembled = ''

  const wrapped: MercuryTurnCallbacks = {
    onOrders: callbacks.onOrders,
    onAnswerDelta: (text) => {
      assembled += text
      callbacks.onAnswerDelta?.(text)
    },
    onCompleted: (finalText) => {
      assembled = finalText || assembled
      callbacks.onCompleted?.(assembled)
    },
    onError: callbacks.onError,
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (value) {
        buffer += decoder.decode(value, { stream: true })
        buffer = consumeSseBuffer(buffer, wrapped)
      }
      if (done) break
    }

    buffer += decoder.decode()
    if (buffer.trim()) {
      dispatchSseBlock(normalizeSseNewlines(buffer), wrapped)
    }

    if (!assembled.trim()) {
      wrapped.onError?.('没有收到回复，请稍后再试')
      throw new Error('没有收到回复')
    }
  } finally {
    reader.releaseLock()
  }
}
