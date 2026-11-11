import type { SimulateRequest, SimulateResponse } from './types'

export async function simulate(request: SimulateRequest): Promise<SimulateResponse> {
  const response = await fetch('/api/simulate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })

  if (!response.ok) {
    let message = `request failed with HTTP ${response.status}`
    try {
      const body = (await response.json()) as { error?: string }
      if (body.error) {
        message = body.error
      }
    } catch {
      // Body was not JSON; keep the status-based message.
    }
    throw new Error(message)
  }

  return (await response.json()) as SimulateResponse
}
