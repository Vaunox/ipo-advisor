import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useBoard, useCalibration, useHealth } from '../api/hooks'
import { recalibrationCount } from '../recalib'
import { toast } from '../toast'
import {
  type Costs,
  type Density,
  type NotifPrefs,
  type Startup,
  type ThemeMode,
  getCosts,
  getDensity,
  getNotifications,
  getStartup,
  getThemeMode,
  setCosts,
  setDensity,
  setNotifications,
  setStartup,
  setThemeMode,
} from '../state/prefs'

function Switch({ on, onToggle }: { on: boolean; onToggle: () => void }) {
  return (
    <div
      className={on ? 'switch on' : 'switch'}
      role="switch"
      aria-checked={on}
      tabIndex={0}
      onClick={onToggle}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onToggle()
        }
      }}
    />
  )
}

export function Settings() {
  const qc = useQueryClient()
  const health = useHealth()
  const board = useBoard()
  const cal = useCalibration()
  const lastRefresh =
    board.dataUpdatedAt > 0
      ? new Date(board.dataUpdatedAt).toLocaleTimeString('en-US', {
          timeZone: 'Asia/Kolkata',
          hour12: true,
          hour: 'numeric',
          minute: '2-digit',
          second: '2-digit',
        })
      : null
  const [theme, setTheme] = useState<ThemeMode>(getThemeMode())
  const [density, setDens] = useState<Density>(getDensity())
  const [notif, setNotifState] = useState<NotifPrefs>(getNotifications())
  const [costs, setCostsState] = useState<Costs>(getCosts())
  const [startup, setStartupState] = useState<Startup>(getStartup())
  const engineUp = health.data?.status === 'ok'

  const updateCost = (k: keyof Costs, v: string) => {
    const next = { ...costs, [k]: parseFloat(v) || 0 }
    setCostsState(next)
    setCosts(next)
    void qc.invalidateQueries({ queryKey: ['history'] })
  }

  const toggleStartup = (k: keyof Startup) => {
    const next = { ...startup, [k]: !startup[k] }
    setStartupState(next)
    setStartup(next)
    const api = (window as unknown as { ipoDesktop?: { setStartupSettings?: (s: Startup) => void } })
      .ipoDesktop
    if (api?.setStartupSettings) api.setStartupSettings(next)
    else toast('Saved — applies when running the desktop app')
  }

  const pickTheme = (m: ThemeMode) => {
    setThemeMode(m)
    setTheme(m)
  }
  const pickDensity = (d: Density) => {
    setDensity(d)
    setDens(d)
  }
  const toggle = (k: keyof NotifPrefs) => {
    const next = { ...notif, [k]: !notif[k] }
    setNotifState(next)
    setNotifications(next)
  }
  const restartEngine = () => {
    const api = (window as unknown as { ipoDesktop?: { restartEngine?: () => void } }).ipoDesktop
    if (api?.restartEngine) {
      api.restartEngine()
      toast('Restarting engine…')
    } else {
      toast('Engine restart is available in the desktop app')
    }
  }

  return (
    <div className="set-grid">
      <div className="card">
        <h3 className="sec">Notifications</h3>
        <div className="set-row">
          <div className="k">Native OS notifications</div>
          <Switch on={notif.native} onToggle={() => toggle('native')} />
        </div>
        <div className="set-row">
          <div className="k">
            Alert on APPLY crossing<small>when a verdict crosses into APPLY</small>
          </div>
          <Switch on={notif.applyCrossing} onToggle={() => toggle('applyCrossing')} />
        </div>
        <div className="set-row">
          <div className="k">
            Alert on any verdict change<small>MARGINAL / SKIP transitions</small>
          </div>
          <Switch on={notif.anyChange} onToggle={() => toggle('anyChange')} />
        </div>
        <div className="set-row">
          <div className="k">Quiet hours (10 PM – 8 AM IST)</div>
          <Switch on={notif.quiet} onToggle={() => toggle('quiet')} />
        </div>
      </div>

      <div className="card">
        <h3 className="sec">Broker cost assumptions</h3>
        <div className="set-row">
          <div className="k">
            STT on sell (%)<small>listing-day delivery sell</small>
          </div>
          <input className="num-in" value={costs.stt} onChange={(e) => updateCost('stt', e.target.value)} />
        </div>
        <div className="set-row">
          <div className="k">
            DP charge (₹, flat)<small>per ISIN per sell-day</small>
          </div>
          <input className="num-in" value={costs.dp} onChange={(e) => updateCost('dp', e.target.value)} />
        </div>
        <div className="set-row">
          <div className="k">Exchange + GST + SEBI (%)</div>
          <input className="num-in" value={costs.oth} onChange={(e) => updateCost('oth', e.target.value)} />
        </div>
        <div className="set-row">
          <div className="k">Effect</div>
          <div className="pending">applied to net-of-cost gains in History</div>
        </div>
      </div>

      <div className="card">
        <h3 className="sec">Appearance</h3>
        <div className="set-row">
          <div className="k">Theme</div>
          <div className="seg2">
            {(['dark', 'light', 'system'] as ThemeMode[]).map((m) => (
              <button key={m} className={theme === m ? 'on' : ''} onClick={() => pickTheme(m)}>
                {m[0].toUpperCase() + m.slice(1)}
              </button>
            ))}
          </div>
        </div>
        <div className="set-row">
          <div className="k">Density</div>
          <div className="seg2">
            {(['comfortable', 'compact'] as Density[]).map((d) => (
              <button key={d} className={density === d ? 'on' : ''} onClick={() => pickDensity(d)}>
                {d[0].toUpperCase() + d.slice(1)}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="card">
        <h3 className="sec">Startup &amp; tray</h3>
        <div className="set-row">
          <div className="k">
            Launch on system startup<small>open the app when Windows starts</small>
          </div>
          <Switch on={startup.launchOnStartup} onToggle={() => toggleStartup('launchOnStartup')} />
        </div>
        <div className="set-row">
          <div className="k">
            Minimize to tray on close<small>keep the engine running in the background</small>
          </div>
          <Switch on={startup.minimizeToTray} onToggle={() => toggleStartup('minimizeToTray')} />
        </div>
        <div className="set-row">
          <div className="k">
            Start minimized<small>launch to the tray, no window</small>
          </div>
          <Switch on={startup.startMinimized} onToggle={() => toggleStartup('startMinimized')} />
        </div>
        <div className="set-row">
          <div className="k">Scope</div>
          <div className="pending">applied by the desktop shell</div>
        </div>
      </div>

      <div className="card">
        <h3 className="sec">Engine</h3>
        <div className="set-row">
          <div className="k">Status</div>
          <div className="health">
            <span className={engineUp ? 'dot' : 'dot down'} />
            {engineUp ? 'online' : health.isError ? 'offline' : 'connecting…'}
          </div>
        </div>
        <div className="set-row">
          <div className="k">
            Last refresh<small>verdicts last pulled from the engine</small>
          </div>
          <div className="mono" style={{ fontSize: 12, color: 'var(--tx2)' }}>
            {lastRefresh ? `${lastRefresh} IST` : '—'}
          </div>
        </div>
        <div className="set-row">
          <div className="k">Calibrator</div>
          <div className="mono" style={{ fontSize: 12, color: 'var(--tx2)' }}>
            {cal.data ? (
              <>
                reliability gate{' '}
                <span style={{ color: cal.data.gate_passed ? 'var(--apply)' : 'var(--marginal)' }}>
                  {cal.data.gate_passed ? 'PASSED' : 'NOT PASSED'}
                </span>{' '}
                · {cal.data.version}
              </>
            ) : (
              '—'
            )}
          </div>
        </div>
        <div className="set-row">
          <div className="k">Recalibration</div>
          <div className="mono" style={{ fontSize: 12, color: 'var(--tx2)' }}>
            re-fit {recalibrationCount()}× · quarterly
          </div>
        </div>
        {cal.data && (
          <div className="set-row">
            <div className="k">Held-out metrics</div>
            <div className="mono" style={{ fontSize: 12, color: 'var(--tx2)' }}>
              {cal.data.ece != null ? `ECE ${cal.data.ece.toFixed(3)} · AUC ${cal.data.auc?.toFixed(2)}` : '—'}
            </div>
          </div>
        )}
        <div className="set-row">
          <div className="k">Actions</div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              className="btn"
              onClick={() => {
                void qc.invalidateQueries()
                toast('Refreshing verdicts…')
              }}
            >
              Refresh now
            </button>
            <button className="btn danger" onClick={restartEngine}>
              Restart engine
            </button>
          </div>
        </div>
      </div>

      <div className="card">
        <h3 className="sec">Model controls</h3>
        <div className="about">
          Verdict thresholds, feature weights, and the calibrator are <b>not editable here</b>, by
          design. The app displays the gated engine's output; it never re-scores or re-derives a
          verdict, so there is no knob that could change a number the reliability gate blessed.
        </div>
      </div>

      <div className="card">
        <h3 className="sec">Keyboard shortcuts</h3>
        <div className="set-row"><div className="k">Search / command palette</div><span><kbd>Ctrl K</kbd><kbd>/</kbd></span></div>
        <div className="set-row"><div className="k">Go to Live · Upcoming</div><span><kbd>g l</kbd><kbd>g u</kbd></span></div>
        <div className="set-row"><div className="k">Go to History · Settings</div><span><kbd>g h</kbd><kbd>g s</kbd></span></div>
        <div className="set-row"><div className="k">Toggle light / dark</div><kbd>t</kbd></div>
        <div className="set-row"><div className="k">Show all shortcuts</div><kbd>?</kbd></div>
      </div>

      <div className="card full">
        <h3 className="sec">About</h3>
        <div className="about">
          <b>IPO Advisor</b> v0.7.0 · Windows desktop (Electron shell + Python FastAPI engine
          sidecar). Mainboard IPOs only.
        </div>
        <div className="disclaimer">
          Engineering/research reference — not financial advice. The operator is not a
          SEBI-registered adviser. A calibrated probability is an estimate, not an assurance — a
          well-calibrated 70% still fails ~30% of the time. GMP is not a scoring input. The app is{' '}
          <b>advisory only</b>: it displays verdicts and places no orders.
        </div>
      </div>
    </div>
  )
}
