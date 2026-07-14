import { useState } from 'react'
import { useAllotment } from '../api/hooks'
import type { AllotmentRow, RegistrarInfo } from '../api/types'
import { Loading } from '../components/Loading'

// v3 V3-6 — the Allotment tab. Routing convenience only: for each IPO past its close, show the
// registrar and DEEP-LINK OUT to the registrar's own allotment-check page. We never collect a PAN
// (the user enters it on the registrar's site) and never show a value the cache didn't provide.
// Registrar data is display-only and comes from a store entirely separate from the model.

const fmtDate = (iso: string): string =>
  new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })

const fmtWhen = (iso: string): string =>
  new Date(iso).toLocaleString('en-IN', {
    day: 'numeric',
    month: 'short',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  })

interface DesktopBridge {
  openExternal?: (url: string) => Promise<boolean>
}

// Open the registrar's page in the user's real browser. Desktop routes through the shell (which
// re-validates https); browser/dev falls back to a new tab. Only ever called with an https URL.
function openRegistrar(url: string): void {
  const api = (window as unknown as { ipoDesktop?: DesktopBridge }).ipoDesktop
  if (api?.openExternal) void api.openExternal(url)
  else window.open(url, '_blank', 'noopener,noreferrer')
}

const isHttps = (url: string | null): url is string => !!url && /^https:\/\//i.test(url)

function ContactBlock({ r }: { r: RegistrarInfo }) {
  const lines: [string, string][] = []
  if (r.email) lines.push(['Email', r.email])
  if (r.contact_number) lines.push(['Phone', r.contact_number])
  if (r.contact_name) lines.push(['Contact', r.contact_name])
  if (!lines.length) return <div className="al-contact-empty">No contact details published.</div>
  return (
    <div className="al-contact">
      {lines.map(([k, v]) => (
        <div className="al-contact-row" key={k}>
          <span className="al-contact-k">{k}</span>
          <span className="al-contact-v mono">{v}</span>
        </div>
      ))}
    </div>
  )
}

function AllotmentCard({ row }: { row: AllotmentRow }) {
  const [showContact, setShowContact] = useState(false)
  const reg = row.registrar
  const listed = row.stage === 'listed'
  const hasContact = !!reg && (!!reg.email || !!reg.contact_number || !!reg.contact_name)
  return (
    <div className="al-card">
      <div className="al-top">
        <div className="al-co">
          <div className="name">{row.name}</div>
          <small>
            closed {fmtDate(row.close_date)}
            {row.listing_date ? ` · listed ${fmtDate(row.listing_date)}` : ''}
          </small>
        </div>
        <span className={`al-stage ${listed ? 'listed' : 'awaiting'}`}>
          {listed ? 'Listed' : 'Awaiting allotment'}
        </span>
      </div>

      {reg ? (
        <div className="al-reg">
          <span className="al-reg-label">Registrar</span>
          <span className="al-reg-name">{reg.name ?? reg.short ?? 'Registrar'}</span>
        </div>
      ) : (
        <div className="al-reg al-reg-missing">Registrar not yet available for this IPO.</div>
      )}

      <div className="al-actions">
        {reg && isHttps(reg.website) ? (
          <button className="btn al-check" onClick={() => openRegistrar(reg.website as string)}>
            Check allotment ↗
          </button>
        ) : (
          <span className="al-nolink">
            {reg ? 'Registrar site unavailable' : 'Link appears once the registrar is published'}
          </span>
        )}
        {hasContact && (
          <button
            className="btn ghost"
            aria-expanded={showContact}
            onClick={() => setShowContact((s) => !s)}
          >
            Contact {showContact ? '▲' : '▾'}
          </button>
        )}
      </div>
      {showContact && reg && <ContactBlock r={reg} />}
    </div>
  )
}

export function Allotment({ onOpen: _onOpen }: { onOpen: (id: string) => void }) {
  const { data, isLoading, isError, refetch } = useAllotment()

  if (isLoading) return <Loading label="Loading allotment…" />
  if (isError || !data)
    return (
      <div className="state">
        <h3>Couldn't load allotment</h3>
        <p>The engine isn't responding.</p>
        <button className="btn" onClick={() => void refetch()}>
          Retry
        </button>
      </div>
    )

  if (!data.rows.length)
    return (
      <div className="state">
        <h3>No IPOs at the allotment stage</h3>
        <p>
          Once an IPO's book closes it appears here with its registrar and a link to check
          allotment on the registrar's own site — through listing day and a few days after.
        </p>
      </div>
    )

  return (
    <>
      {data.available ? (
        <div className="al-fresh">
          Registrar data as of {data.refreshed_at ? fmtWhen(data.refreshed_at) : '—'} · you check
          allotment on the registrar's own site — no PAN is entered or stored here.
        </div>
      ) : (
        <div className="al-degraded">
          <b>Registrar details not loaded.</b> The IPOs below are at the allotment stage, but the
          registrar cache hasn't been refreshed yet — run <span className="mono">
            scripts/refresh_allotment.py
          </span>. Details appear once it's populated; nothing here is shown as current when it isn't.
        </div>
      )}
      <div className="al-grid">
        {data.rows.map((row) => (
          <AllotmentCard key={row.ipo_id} row={row} />
        ))}
      </div>
    </>
  )
}
