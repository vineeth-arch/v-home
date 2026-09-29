import { useEffect, useState } from 'react'
import { getHousehold, listRows, saveRow, type Row } from './api'
import { localDate } from '../shared/daily'
import { inWeek, mondayOf, type WeeklyPayload } from '../shared/week'

const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

/** One plan, one task, one dream step for the week. Saved as a single ritual_selections row per week. */
export function Weekly({ hh }: { hh: string }) {
  const [tz, setTz] = useState('Asia/Kolkata')
  const [events, setEvents] = useState<Row[]>([]); const [tasks, setTasks] = useState<Row[]>([]); const [dreams, setDreams] = useState<Row[]>([]); const [ideas, setIdeas] = useState<Row[]>([])
  const [existing, setExisting] = useState<Row | null>(null)
  const [v, setV] = useState<WeeklyPayload>({}); const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null); const [busy, setBusy] = useState(false)
  const monday = (t = tz) => mondayOf(localDate(new Date(), t))

  const load = async () => {
    const [h, ev, tk, dr, rs, id] = await Promise.all([getHousehold(), listRows('events'), listRows('tasks'), listRows('dreams'), listRows('ritual_selections'), listRows('ideas')])
    setTz(h.timezone); setEvents(ev); setTasks(tk.filter((t) => !t.done && t.kind === 'task')); setDreams(dr); setIdeas(id.filter((i) => i.status !== 'archived'))
    const cur = rs.find((r) => r.slot === 'weekly' && r.day === mondayOf(localDate(new Date(), h.timezone))) ?? null
    setExisting(cur); if (cur) setV(cur.payload as WeeklyPayload)
  }
  useEffect(() => { void load().catch((x) => setMsg({ ok: false, text: x.message })) }, [])

  const thisWeek = events.filter((e) => inWeek(localDate(new Date(String(e.starts_at)), tz), monday()))
  const dream = dreams.find((d) => d.id === v.dreamId)

  const saveSelection = async (base: Row | null, payload: WeeklyPayload) => {
    const values = { day: monday(), slot: 'weekly', payload }
    try { return await saveRow('ritual_selections', hh, base, values) }
    catch (x) {
      // both partners saving at once: the unique index rejects the second insert. Reload and retry as an update, once.
      if (base || !/duplicate key/i.test((x as Error).message)) throw x
      const rs = await listRows('ritual_selections')
      const cur = rs.find((r) => r.slot === 'weekly' && r.day === monday()) ?? null
      return saveRow('ritual_selections', hh, cur, values)
    }
  }
  const save = async () => {
    setBusy(true); setMsg(null)
    try {
      const payload: WeeklyPayload = { ...v }
      const before = existing?.payload as WeeklyPayload | undefined
      if (v.dreamId && v.stepTitle?.trim() && (before?.stepTitle !== v.stepTitle || before?.dreamId !== v.dreamId)) await saveRow('dream_steps', hh, null, { dream_id: v.dreamId, title: v.stepTitle.trim() })
      const r = await saveSelection(existing, payload)
      if ('conflict' in r) { setMsg({ ok: false, text: 'Someone just changed this week. Reloaded, review and save again.' }); await load() }
      else if ('denied' in r) setMsg({ ok: false, text: 'You no longer have access to this.' })
      else { setMsg({ ok: true, text: 'Saved. It shows on the TV under Us, This Week.' }); await load() }
    } catch (x) { setMsg({ ok: false, text: (x as Error).message }) } finally { setBusy(false) }
  }
  const opt = (rows: Row[], label: (r: Row) => string) => rows.map((r) => <option key={r.id} value={r.id}>{label(r)}</option>)
  return <div><h1>This week</h1><div className="dim">Choose one plan, one task and one small dream step together. Week of {monday()}.</div>
    <label>A plan for this week</label>
    <select value={v.eventId ?? ''} onChange={(e) => setV({ ...v, eventId: e.target.value || undefined })}><option value="">None yet</option>{opt(thisWeek, (r) => `${r.title} · ${new Date(String(r.starts_at)).toLocaleDateString()}`)}</select>
    {thisWeek.length === 0 && <div className="dim">No plans this week. Add one under Plans.</div>}
    <label>A household task</label>
    <select value={v.taskId ?? ''} onChange={(e) => setV({ ...v, taskId: e.target.value || undefined })}><option value="">None yet</option>{opt(tasks, (r) => String(r.title))}</select>
    <label>A dream to move forward</label>
    <select value={v.dreamId ?? ''} onChange={(e) => { const d = dreams.find((x) => x.id === e.target.value); setV({ ...v, dreamId: e.target.value || undefined, stepTitle: v.stepTitle || (d ? String(d.next_step ?? '') : '') }) }}><option value="">None yet</option>{opt(dreams, (r) => String(r.title))}</select>
    {dream && <><label>The small step</label><input value={v.stepTitle ?? ''} onChange={(e) => setV({ ...v, stepTitle: e.target.value })} /></>}
    <label>Date night</label>
    <select value={v.dateNight?.day ?? ''} onChange={(e) => setV({ ...v, dateNight: e.target.value ? { ...v.dateNight, day: e.target.value } : undefined })}><option value="">Not this week</option>{DAYS.map((d) => <option key={d} value={d}>{d}</option>)}</select>
    {v.dateNight && <><label>What we'll do (pick an idea or write one)</label>
      <select value={v.dateNight.ideaId ?? ''} onChange={(e) => setV({ ...v, dateNight: { ...v.dateNight!, ideaId: e.target.value || undefined } })}><option value="">Write my own</option>{opt(ideas, (r) => String(r.title))}</select>
      {!v.dateNight.ideaId && <input placeholder="e.g. Dinner at the rooftop place" value={v.dateNight.text ?? ''} onChange={(e) => setV({ ...v, dateNight: { ...v.dateNight!, text: e.target.value } })} />}</>}
    {msg && <div className={msg.ok ? 'ok' : 'err'}>{msg.text}</div>}
    <div className="row" style={{ marginTop: 16 }}><button className="pbtn primary" disabled={busy} onClick={() => void save()}>{existing ? 'Update this week' : 'Save this week'}</button></div></div>
}
