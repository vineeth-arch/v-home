import { useEffect, useMemo, useRef, useState } from 'react'
import { useApp } from './state'
import { fmtTime } from './ui'
import { ambientQueue, type AmbientPhoto } from '../shared/ambient'
import { localDate } from '../shared/daily'
import type { Snapshot } from '../shared/model'
import { pickDaily } from '../shared/reflections'
import type { Platform } from '../adapters/platform'
import './ambient.css'

const EVERY_MS = 45_000

/**
 * Keep the TV's own screensaver from covering the photo frame while it is open.
 * Pattern from zzeppieri/webos-custom-home (MIT, (c) 2026 zzeppieri): answer tvpower's request with ack:false.
 * Best effort: if the TV denies it, its screensaver simply takes over.
 */
function useNoScreensaver(platform: Platform) {
  useEffect(() => {
    if (platform.simulated) return
    const clientName = 'com.designinnsaeit.vhome'
    return platform.subscribe('luna://com.webos.service.tvpower/power/registerScreenSaverRequest', { clientName }, (r) => {
      const ts = 'ok' in r && r.ok ? r.data.timestamp : undefined
      if (ts !== undefined) void platform.call('luna://com.webos.service.tvpower/power/responseScreenSaverRequest', { clientName, ack: false, timestamp: ts })
    })
  }, [platform])
}

/** Photos the TV can show: moments plus dream/idea pictures that have a resolved image. None for guests. Shared with the Home photo card. */
export function tvPhotos(snap: Snapshot, images: Record<string, string>, guest: boolean): AmbientPhoto[] {
  return guest ? [] : [
    ...snap.moments,
    ...snap.dreams.filter((d) => d.imagePath).map((d) => ({ path: d.imagePath!, caption: d.title })),
    ...snap.ideas.filter((i) => i.imagePath).map((i) => ({ path: i.imagePath!, caption: i.title })),
  ].filter((p) => images[p.path])
}

/** Idle photo frame: photos marked Show on TV, a clock, the weather and one reflection. Any key or click closes it. */
export function Ambient({ onClose }: { onClose: () => void }) {
  const { snap, now, tz, guest, weather, images, platform } = useApp()
  useNoScreensaver(platform)
  useEffect(() => {
    // The OK press that opened the frame also yields the button's native click; ignore input for a moment so it can't close it again.
    const openedAt = Date.now()
    const close = (e: Event) => { if (Date.now() - openedAt < 400) return; e.preventDefault(); e.stopImmediatePropagation(); onClose() }
    addEventListener('keydown', close, true); addEventListener('click', close, true)
    return () => { removeEventListener('keydown', close, true); removeEventListener('click', close, true) }
  }, [onClose])

  const today = localDate(now, tz)
  const photos = useMemo(() => tvPhotos(snap, images, guest), [snap, images, guest])
  const lastShown = useRef(new Map<string, number>())
  const queue = useMemo(() => ambientQueue(photos, today, lastShown.current), [photos, today])

  // Two stacked layers; the next photo is decoded before it fades in, so the fade never shows a half-loaded image.
  const [layers, setLayers] = useState<[string | null, string | null]>([null, null])
  const [front, setFront] = useState(0)
  const [pos, setPos] = useState(0)
  const cur = queue.length ? queue[pos % queue.length] : undefined
  useEffect(() => {
    if (!cur) return
    let dead = false
    const url = images[cur.path], img = new Image()
    img.src = url
    void img.decode().catch(() => undefined).then(() => {
      if (dead) return
      lastShown.current.set(cur.path, Date.now())
      setLayers((l) => { const n: [string | null, string | null] = [...l]; n[front ^ 1] = url; return n })
      setFront((f) => f ^ 1)
    })
    return () => { dead = true }
  }, [cur?.path]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (queue.length < 2) return
    const id = setInterval(() => setPos((p) => p + 1), EVERY_MS)
    return () => clearInterval(id)
  }, [queue.length])

  const refl = guest ? undefined : pickDaily(snap.household.id || snap.household.name, today, 'evening', snap.household.hiddenReflections, snap.quotes)
  const caption = cur?.yearsAgo ? `${cur.yearsAgo === 1 ? 'A year' : `${cur.yearsAgo} years`} ago today${cur.caption ? ` · ${cur.caption}` : ''}` : cur?.caption
  return (
    <div className="ambient" role="dialog" aria-label="Photo frame">
      {layers.map((src, i) => src && <img key={i} className={`amb-img ${i === front ? 'on' : ''}`} src={src} alt="" />)}
      <div className="amb-info">
        <div className="amb-clock">{fmtTime(now, tz)}</div>
        {weather?.showCurrent && <div className="amb-wx">{weather.tempC}° {weather.label}{weather.nextHours?.length ? ` · later ${weather.nextHours.map((h) => `${h.tempC}°`).join(' ')}` : ''}</div>}
        {caption && <div className="amb-cap">{caption}</div>}
        {!cur && refl && <div className="amb-refl">{refl.text}</div>}
      </div>
      <div className="amb-hint">Press any button to return</div>
    </div>
  )
}
