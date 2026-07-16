import { useEffect, useMemo, useState } from 'react'
import { useAllotment, useBoard, useCalibration, useHealth } from './api/hooks'
import { CommandPalette } from './components/CommandPalette'
import { IconAlert } from './components/Icons'
import { Sidebar } from './components/Sidebar'
import { TopBar } from './components/TopBar'
import type { View } from './nav'
import { useCrossingNotifications } from './notifications'
import { recalibrationCount } from './recalib'
import { Allotment } from './screens/Allotment'
import { ConsoleLog } from './screens/ConsoleLog'
import { Detail } from './screens/Detail'
import { History } from './screens/History'
import { Live } from './screens/Live'
import { Settings } from './screens/Settings'
import { Upcoming } from './screens/Upcoming'
import { getDevConsole, setThemeMode, useDevConsole } from './state/prefs'
import { Toaster } from './components/Toaster'

const TITLES: Record<View, [string, string]> = {
  live: ['Live signals', 'mainboard · updated live · IST'],
  upcoming: ['Upcoming IPOs', 'mainboard calendar · anchor days flagged'],
  allotment: ['Allotment', 'check allotment on the registrar’s own site · no PAN stored here'],
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

const HelpOverlay = ({ onClose, devConsole }: { onClose: () => void; devConsole: boolean }) => (
  <div className="overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
    <div className="help-card">
      <div className="hh">Keyboard shortcuts</div>
      <div className="help-body">
        <div className="hk"><span>Search / command palette</span><span><kbd>Ctrl K</kbd><kbd>/</kbd></span></div>
        <div className="hk"><span>Go to Live · Upcoming</span><span><kbd>g l</kbd><kbd>g u</kbd></span></div>
        <div className="hk"><span>Go to History · Settings</span><span><kbd>g h</kbd><kbd>g s</kbd></span></div>
        <div className="hk"><span>Toggle light / dark</span><kbd>t</kbd></div>
        {devConsole && (
          <div className="hk"><span>Toggle console log</span><kbd>`</kbd></div>
        )}
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
  // v3 V3-16: the debug console. `devConsole` is the durable enable pref (Settings); `consoleOpen`
  // is ephemeral view-state toggled by the ` key. Reading devConsole reactively means turning it
  // OFF in Settings closes an open console (and deadens the key) at once.
  const [consoleOpen, setConsoleOpen] = useState(false)
  const devConsole = useDevConsole()
  const health = useHealth()
  const board = useBoard()
  const calibration = useCalibration()
  const allotment = useAllotment()
  const engineUp = health.isSuccess && health.data?.status === 'ok'
  const engineDown = health.isError
  useCrossingNotifications() // native OS toast on a new APPLY crossing (desktop shell only)

  // Nav count chips: the size of each section, derived from the board with the SAME partitions the
  // Live / Upcoming / History screens render (no extra fetch, no fabricated numbers). `live` must
  // match the Live screen (open now or closes today) — NOT the raw record count, which also holds
  // closed/listed rows the Live screen filters out.
  const counts = useMemo(() => {
    const rows = board.data ?? []
    const t = new Date()
    t.setHours(0, 0, 0, 0)
    const midnight = (d: string) => +new Date(`${d}T00:00:00`)
    let live = 0
    let upcoming = 0
    let history = 0
    for (const r of rows) {
      const listed = r.listing_date != null && midnight(r.listing_date) <= +t
      if (listed || midnight(r.close_date) < +t) {
        history += 1 // listed, or the book has closed → History's domain (outcome or awaiting)
      } else {
        upcoming += 1 // not listed and book not yet closed → on the calendar
        if (midnight(r.open_date) <= +t) live += 1 // …and already open → live now
      }
    }
    return { live, upcoming, history }
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
        else if (e.key === 'a') navigate('allotment')
        else if (e.key === 'h') navigate('history')
        else if (e.key === 's') navigate('settings')
        return
      }
      if (e.key === 'g') {
        gPending = true
        gTimer = window.setTimeout(() => (gPending = false), 900)
      } else if (e.key === 't') {
        setThemeMode(document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light')
      } else if (e.key === '`' && getDevConsole()) {
        // v3 V3-16: backtick toggles the console open/closed — but only when enabled in Settings
        // (getDevConsole() is read live, so a fresh install / disabled state leaves the key dead).
        setConsoleOpen((o) => !o)
      } else if (e.key === '/') {
        e.preventDefault()
        setPaletteOpen(true)
      } else if (e.key === '?') {
        setHelpOpen(true)
      } else if (e.key === 'Escape') {
        setPaletteOpen(false)
        setHelpOpen(false)
        setConsoleOpen(false)
        setDetailId((d) => (d ? null : d))
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  // Disabling the console in Settings closes it if it's open (the ` key is already dead by then).
  useEffect(() => {
    if (!devConsole) setConsoleOpen(false)
  }, [devConsole])

  const [title, sub] = detailId ? ['Verdict detail', 'read-only · engine output verbatim'] : TITLES[view]

  return (
    <div className="app">
      <Sidebar
        view={view}
        onNavigate={navigate}
        counts={{ ...counts, allotment: allotment.data?.rows.length ?? 0 }}
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
            <History onOpen={setDetailId} />
          ) : view === 'upcoming' ? (
            <Upcoming onOpen={setDetailId} />
          ) : view === 'allotment' ? (
            <Allotment onOpen={setDetailId} />
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
      {helpOpen && <HelpOverlay onClose={() => setHelpOpen(false)} devConsole={devConsole} />}
      {consoleOpen && devConsole && <ConsoleLog onClose={() => setConsoleOpen(false)} />}
      <Toaster />
    </div>
  )
}
