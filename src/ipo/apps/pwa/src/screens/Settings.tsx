import { useState } from 'react'
import { useCalibration, useHealth } from '../api/hooks'
import { recalibrationCount } from '../recalib'
import {
  type Density,
  type ThemeMode,
  getDensity,
  getThemeMode,
  setDensity,
  setThemeMode,
} from '../state/prefs'

function Switch({ on, onToggle }: { on: boolean; onToggle: () => void }) {
  return <div className={on ? 'switch on' : 'switch'} role="switch" aria-checked={on} onClick={onToggle} />
}

export function Settings() {
  const health = useHealth()
  const cal = useCalibration()
  const [theme, setTheme] = useState<ThemeMode>(getThemeMode())
  const [density, setDens] = useState<Density>(getDensity())
  const [notif, setNotif] = useState({ native: true, applyCrossing: true, anyChange: false, quiet: true })
  const engineUp = health.data?.status === 'ok'

  const pickTheme = (m: ThemeMode) => {
    setThemeMode(m)
    setTheme(m)
  }
  const pickDensity = (d: Density) => {
    setDensity(d)
    setDens(d)
  }
  const toggle = (k: keyof typeof notif) => setNotif((n) => ({ ...n, [k]: !n[k] }))

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
          <div className="k">Quiet hours (22:00–08:00 IST)</div>
          <Switch on={notif.quiet} onToggle={() => toggle('quiet')} />
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
        <h3 className="sec">Engine</h3>
        <div className="set-row">
          <div className="k">Status</div>
          <div className="health">
            <span className={engineUp ? 'dot' : 'dot down'} />
            {engineUp ? 'online' : health.isError ? 'offline' : 'connecting…'}
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
      </div>

      <div className="card">
        <h3 className="sec">Model controls</h3>
        <div className="about">
          Verdict thresholds, feature weights, and the calibrator are <b>not editable here</b>, by
          design. The app displays the gated engine's output; it never re-scores or re-derives a
          verdict, so there is no knob that could change a number the reliability gate blessed.
        </div>
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
