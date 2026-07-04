import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import ReactDOM from 'react-dom/client'
import { App } from './App'
import { applyDensity, applyTheme, getThemeMode, hydrateFromDesktop } from './state/prefs'
import './styles.css'

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchInterval: 30_000, retry: 1, staleTime: 10_000 } },
})

// In the desktop shell, load durable prefs from the app config file before first paint (a fast IPC
// round-trip; a no-op in the browser / preview). Then apply the persisted theme + density and mount.
async function start(): Promise<void> {
  await hydrateFromDesktop()
  applyTheme(getThemeMode())
  applyDensity()
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </React.StrictMode>,
  )
}

void start()
