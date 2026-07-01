import { useState } from 'react'
import { useBoard, useCalibration, useHealth } from './api/hooks'
import { IconAlert } from './components/Icons'
import { Sidebar } from './components/Sidebar'
import { TopBar } from './components/TopBar'
import type { View } from './nav'
import { recalibrationCount } from './recalib'
import { Detail } from './screens/Detail'
import { History } from './screens/History'
import { Live } from './screens/Live'

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

const Placeholder = ({ label }: { label: string }) => (
  <div className="state">
    <h3>{label}</h3>
    <p>This screen lands in the next build step.</p>
  </div>
)

export function App() {
  const [view, setView] = useState<View>('live')
  const [detailId, setDetailId] = useState<string | null>(null)
  const health = useHealth()
  const board = useBoard()
  const calibration = useCalibration()
  const engineUp = health.isSuccess && health.data?.status === 'ok'
  const engineDown = health.isError

  const navigate = (v: View) => {
    setDetailId(null)
    setView(v)
  }

  const [title, sub] = detailId ? ['Verdict detail', 'read-only · engine output verbatim'] : TITLES[view]

  return (
    <div className="app">
      <Sidebar
        view={view}
        onNavigate={navigate}
        counts={{ live: board.data?.length }}
        engineUp={engineUp}
        gatePassed={calibration.data?.gate_passed ?? true}
        recalibrations={recalibrationCount()}
      />
      <main className="main">
        <TopBar title={title} sub={sub} />
        <div className="content">
          {engineDown ? (
            <EngineDown onRetry={() => void health.refetch()} />
          ) : detailId ? (
            <Detail id={detailId} onBack={() => setDetailId(null)} />
          ) : view === 'live' ? (
            <Live onOpen={setDetailId} />
          ) : view === 'history' ? (
            <History />
          ) : (
            <Placeholder label={title} />
          )}
        </div>
      </main>
    </div>
  )
}
