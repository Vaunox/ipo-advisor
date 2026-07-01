import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import ReactDOM from 'react-dom/client'
import { App } from './App'
import { applyDensity, applyTheme, getThemeMode } from './state/prefs'
import './styles.css'

// Apply the persisted theme + density before first paint.
applyTheme(getThemeMode())
applyDensity()

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchInterval: 30_000, retry: 1, staleTime: 10_000 } },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
)
