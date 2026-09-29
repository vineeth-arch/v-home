import { useEffect, useRef } from 'react'
import { useApp } from './state'
import { Btn, fmtDay, fmtTime } from './ui'
import type { StudioMetric } from '../shared/model'
import './studio.css'

const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 })
const TILES = ['invoices.invoices_open_total', 'invoices.invoices_overdue', 'outreach.followups_now', 'outreach.leads_open', 'forms.forms_with_clients', 'forms.forms_to_review']
const FRESH_MS = 15 * 60_000

/** Design Innsaeit at a glance: a few calm numbers and the next follow-ups. Amber means "needs you"; never red, no charts. */
export function Studio() {
  const { snap, tz, now, live } = useApp()
  const metrics = snap.studio.metrics
  const by = new Map(metrics.map((m) => [m.key, m]))
  const oldest = metrics.length ? Math.min(...metrics.map((m) => Date.parse(m.fetchedAt))) : 0
  const asked = useRef(0)
  useEffect(() => { // ask the server for fresh numbers while Studio is open; the server throttles too
    if (!live) return
    const tick = () => { if (Date.now() - oldest >= FRESH_MS && Date.now() - asked.current >= FRESH_MS) { asked.current = Date.now(); void live.syncStudio() } }
    tick(); const id = setInterval(tick, 60_000)
    return () => clearInterval(id)
  }, [live, oldest])

  const tiles = TILES.map((k) => by.get(k)).filter((m): m is StudioMetric => !!m)
  const next = (by.get('outreach.followups_next')?.detail.items as { due?: string; stage?: string; name?: string }[] | undefined) ?? []
  const stale = metrics.some((m) => !m.ok)
  if (!metrics.length) return <div className="card"><h2>Studio</h2><div className="dim">No numbers yet. Studio fills in once the business sources are connected (see the phone, Settings, Studio).</div></div>
  return <div className="studio">
    <div className="studio-tiles">{tiles.map((m, i) => {
      const attention = m.detail.attention === true && (m.value ?? 0) > 0
      return <Btn key={m.key} id={`studio-${m.key}`} initial={i === 0} className={`studio-tile ${attention ? 'attn' : ''} ${m.ok ? '' : 'stale'}`}>
        <span className="n">{m.value === null ? '–' : m.detail.unit === 'INR' ? inr.format(m.value) : m.value}</span>
        <span className="l">{m.label}</span>
      </Btn>
    })}</div>
    <div className="studio-next card">
      <h2>Next follow-ups <span className="dim small asof">{stale ? 'Some numbers could not be refreshed · ' : ''}as of {fmtTime(oldest || now, tz)}</span></h2>
      {next.length ? next.map((it, i) => <div className="row" key={i}><span className="t">{it.due ? fmtDay(`${it.due}T12:00:00+05:30`, tz) : ''}</span><span>{it.name ? `${it.name} · ` : ''}{it.stage}</span></div>)
        : <div className="dim">Nothing due this week.</div>}
    </div>
  </div>
}
