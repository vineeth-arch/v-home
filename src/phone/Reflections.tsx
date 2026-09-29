import { useEffect, useState } from 'react'
import { getHousehold, saveHousehold } from './api'
import { Crud } from './Crud'
import { ENTITIES } from './entities'
import { BUNDLED } from '../shared/reflections'

/** Your own reflections (full CRUD) plus a hide/show list for the 40 built-in ones. */
export function Reflections({ hh, me }: { hh: string; me: string }) {
  const [h, setH] = useState<Awaited<ReturnType<typeof getHousehold>> | null>(null)
  const [err, setErr] = useState('')
  const load = () => getHousehold().then(setH).catch((x) => setErr(x.message))
  useEffect(() => { void load() }, [])
  const hidden = (h?.settings.hiddenReflections as string[] | undefined) ?? []
  const toggle = async (id: string) => {
    if (!h) return
    setErr('')
    try { await saveHousehold(h, { settings: { ...h.settings, hiddenReflections: hidden.includes(id) ? hidden.filter((x) => x !== id) : [...hidden, id] } }); await load() } catch (x) { setErr((x as Error).message); void load() }
  }
  return <div>
    <Crud e={ENTITIES.quotes} hh={hh} me={me} />
    <h2>Built-in reflections</h2><div className="dim">Original reflections written for V/HOME. Hide any you don't like.</div>
    {err && <div className="err">{err}</div>}
    {(['morning', 'evening'] as const).map((slot) => <div key={slot}><h2 style={{ fontSize: 18 }}>{slot === 'morning' ? 'Morning' : 'Evening'}</h2>
      {BUNDLED.filter((r) => r.slot === slot).map((r) => <div className="item" key={r.id} style={{ opacity: hidden.includes(r.id) ? 0.55 : 1 }}>
        <span>{r.text}</span><div className="row"><button className={`pbtn ${hidden.includes(r.id) ? '' : 'on'}`} onClick={() => void toggle(r.id)}>{hidden.includes(r.id) ? 'Hidden. Show again' : 'Showing. Hide'}</button></div></div>)}</div>)}
  </div>
}
