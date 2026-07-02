import { useEffect, useMemo, useState } from 'react'
import { useBoard, useCalibration, useHealth } from './api/hooks'
import { CommandPalette } from './components/CommandPalette'
import { IconAlert } from './components/Icons'
import { Sidebar } from './components/Sidebar'
import { TopBar } from './components/TopBar'
import type { View } from './nav'
import { useCrossingNotifications } from './notifications'
import { recalibrationCount } from './recalib'
import { Detail } from './screens/Detail'
import { History } from './screens/History'
import { Live } from './screens/Live'
import { Settings } from './screens/Settings'
import { Upcoming } from './screens/Upcoming'
import { setThemeMode } from './state/prefs'
import { Toaster } from './components/Toaster'

const TITLES: Record<View, [string, string]> = {
  live: ['Live signals', 'mainboard · updated live · IST'],
  upcoming: ['Upcoming IPOs', 'mainboard calendar · anchor days flagged'],
  history: ['History & accountability', 'did the verdicts hold up?'],
  settings: ['Settings', 'operational — model internals are not editable'],
}

function EngineDown({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="enginedown">
      <div className="ic">
        <IconAlert />
      </div>
      <h2>Engine unavailable</h2>
      <p>
        The advisory engine isn't responding. Verdicts can't be shown until it's back — nothing
        here is stale-but-pretending-to-be-live.
      </p>
      <button className="btn" onClick={onRetry}>
        Retry connection
      </button>
    </div>
  )
}

const UncalBanner = () => (
  <div className="uncal-banner">
    <IconAlert />
    <span>
      <b>UNCALIBRATED — reliability gate not passed.</b> Verdicts are shown; probabilities are
      withheld until the calibrator passes its out-of-sample check. No number the gate didn't bless.
    </span>
  </div>
)

const HelpOverlay = ({ onClose }: { onClose: () => void }) => (
  <div className="overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
    <div className="help-card">
      <div className="hh">Keyboard shortcuts</div>
      <div className="help-body">
        <div className="hk"><span>Search / command palette</span><span><kbd>Ctrl K</kbd><kbd>/</kbd></span></div>
        <div className="hk"><span>Go to Live · Upcoming</span><span><kbd>g l</kbd><kbd>g u</kbd></span></div>
        <div className="hk"><span>Go to History · Settings</span><span><kbd>g h</kbd><kbd>g s</kbd></span></div>
        <div className="hk"><span>Toggle light / dark</span><kbd>t</kbd></div>
        <div className="hk"><span>Close · back</span><kbd>Esc</kbd></div>
        <div className="hk"><span>This help</span><kbd>?</kbd></div>
      </div>
    </div>
  </div>
)

export function App() {
  const [view, setView] = useState<View>('live')
  const [detailId, setDetailId] = useState<string | null>(null)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const health = useHealth()
  const board = useBoard()
  const calibration = useCalibration()
  const engineUp = health.isSuccess && health.data?.status === 'ok'
  const engineDown = health.isError
  useCrossingNotifications() // native OS toast on a new APPLY crossing (desktop shell only)

  // Nav count chips: the size of each section, derived from the board (the same partitions the
  // Upcoming / History screens render) — no extra fetch, no fabricated numbers.
  const counts = useMemo(() => {
    const rows = board.data ?? []
    const t = new Date()
    t.setHours(0, 0, 0, 0)
    const midnight = (d: string) => +new Date(`${d}T00:00:00`)
    let upcoming = 0
    let history = 0
    for (const r of rows) {
      const listed = r.listing_date != null && midnight(r.listing_date) <= +t
      if (listed) history += 1
      else if (midnight(r.close_date) >= +t) upcoming += 1
    }
    return { live: rows.length, upcoming, history }
  }, [board.data])

  const navigate = (v: View) => {
    setDetailId(null)
    setView(v)
  }

  // keyboard shortcuts: Ctrl/⌘+K or / (palette), g+l/u/h/s (nav), t (theme), ? (help), Esc (close)
  useEffect(() => {
    let gPending = false
    let gTimer = 0
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName?.toLowerCase()
      const isCmdK = (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k'
      if (isCmdK) {
        e.preventDefault()
        setPaletteOpen(true)
        return
      }
      if (tag === 'input' || tag === 'textarea' || e.ctrlKey || e.metaKey || e.altKey) return
      if (gPending) {
        gPending = false
        window.clearTimeout(gTimer)
        if (e.key === 'l') navigate('live')
        else if (e.key === 'u') navigate('upcoming')
        else if (e.key === 'h') navigate('history')
        else if (e.key === 's') navigate('settings')
        return
      }
      if (e.key === 'g') {
        gPending = true
        gTimer = window.setTimeout(() => (gPending = false), 900)
      } else if (e.key === 't') {
        setThemeMode(document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light')
      } else if (e.key === '/') {
        e.preventDefault()
        setPaletteOpen(true)
      } else if (e.key === '?') {
        setHelpOpen(true)
      } else if (e.key === 'Escape') {
        setPaletteOpen(false)
        setHelpOpen(false)
        setDetailId((d) => (d ? null : d))
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  const [title, sub] = detailId ? ['Verdict detail', 'read-only · engine output verbatim'] : TITLES[view]

  return (
    <div className="app">
      <Sidebar
        view={view}
        onNavigate={navigate}
        counts={counts}
        engineUp={engineUp}
        gatePassed={calibration.data?.gate_passed ?? true}
        recalibrations={recalibrationCount()}
      />
      <main className="main">
        <TopBar
          title={title}
          sub={sub}
          board={board.data ?? []}
          onOpenIpo={setDetailId}
          onSearch={() => setPaletteOpen(true)}
        />
        <div className="content">
          {!engineDown && calibration.data && !calibration.data.gate_passed && <UncalBanner />}
          {engineDown ? (
            <EngineDown onRetry={() => void health.refetch()} />
          ) : detailId ? (
            <Detail id={detailId} onBack={() => setDetailId(null)} />
          ) : view === 'live' ? (
            <Live onOpen={setDetailId} />
          ) : view === 'history' ? (
            <History />
          ) : view === 'upcoming' ? (
            <Upcoming />
          ) : (
            <Settings />
          )}
        </div>
      </main>
      {paletteOpen && (
        <CommandPalette
          board={board.data ?? []}
          onOpenIpo={setDetailId}
          onNav={navigate}
          onClose={() => setPaletteOpen(false)}
        />
      )}
      {helpOpen && <HelpOverlay onClose={() => setHelpOpen(false)} />}
      <Toaster />
    </div>
  )
}
