/**
 * Mercury customer service API client
 * Mirrors the pattern from saleGuide.ts
 */

export interface MercurySessionResponse {
  session_id: string
  created_at: string
}

export interface MercuryTurnCallbacks {
  onAnswerDelta?: (text: string) => void
  onCompleted?: (finalText: string) => void
  onError?: (error: string) => void
}

/**
 * Create a new Mercury session
 */
export async function createMercurySession(): Promise<string> {
  const resp = await fetch('/api/v1/mercury/sessions', {
    method: 'POST',
    credentials: 'include'
  })

  if (!resp.ok) {
    throw new Error(`Failed to create session: ${resp.statusText}`)
  }

  const data: MercurySessionResponse = await resp.json()
  return data.session_id
}

/**
 * Send a message to Mercury and receive streaming response
 */
export async function sendMercuryTurn(
  sessionId: string,
  message: string,
  callbacks: MercuryTurnCallbacks = {}
): Promise<void> {
  const requestId = `req_${Date.now()}`

  const resp = await fetch(`/api/v1/mercury/sessions/${sessionId}/turns/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ message, request_id: requestId })
  })

  if (!resp.ok) {
    throw new Error(`Failed to send message: ${resp.statusText}`)
  }

  // Parse SSE stream
  const reader = resp.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (!line.trim() || !line.startsWith('event:')) continue

        const eventMatch = line.match(/event:\s*(\S+)/)
        const dataMatch = line.match(/data:\s*(.+)/)

        if (!eventMatch || !dataMatch) continue

        const event = eventMatch[1]
        const data = JSON.parse(dataMatch[1])

        switch (event) {
          case 'answer.delta':
            callbacks.onAnswerDelta?.(data.text)
            break
          case 'turn.completed':
            callbacks.onCompleted?.(data.final_text)
            break
          case 'error':
            callbacks.onError?.(data.message)
            break
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}
