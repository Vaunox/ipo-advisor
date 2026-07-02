// Tiny pub/sub toast bus. `toast(msg)` from anywhere; <Toaster/> (rendered once in App) subscribes
// and shows transient confirmations — matching the comp's toast pattern.

export interface ToastMsg {
  id: number
  text: string
}

type Listener = (t: ToastMsg) => void

const listeners = new Set<Listener>()
let seq = 0

export function toast(text: string): void {
  const msg = { id: ++seq, text }
  listeners.forEach((l) => l(msg))
}

export function subscribeToasts(l: Listener): () => void {
  listeners.add(l)
  return () => listeners.delete(l)
}
