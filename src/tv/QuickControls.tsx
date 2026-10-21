import { useState } from 'react'
import { Btn } from './ui'
import { useLayer } from './FocusProvider'
import { useApp } from './state'
import { useTimerActions } from './timerActions'
import { SLEEP_APP } from '../adapters/timer'
import { appsOf } from '../shared/model'
import { PICTURE_MODES } from '../adapters/tvcontrols'

export function ConfirmOff({ onClose }: { onClose: () => void }) {
  const { ctrl, refreshTimer } = useApp()
  const [msg, setMsg] = useState('')
  useLayer('confirm', true, onClose)
  const off = async () => {
    const r = await ctrl.mutate((a) => a.powerOff())
    setMsg(r.kind === 'confirmed' || r.kind === 'handoff' ? 'Turning the TV off…' : 'Could not confirm the request.')
    refreshTimer()
  }
  return (
    <div className="overlay"><div className="panel" style={{ width: 900 }}>
      <h2>Turn the TV off now?</h2>
      <p className="dim">This ends whatever is playing.</p>
      <div className="presets">
        <Btn id="off-yes" scope="confirm" className="primary" onClick={off}>Turn TV off</Btn>
        <Btn id="off-no" scope="confirm" initial onClick={onClose}>Cancel</Btn>
      </div>
      <div className="status-msg warn">{msg}</div>
    </div></div>
  )
}

export function QuickControls({ onClose }: { onClose: () => void }) {
  const { snap, guest, setGuest, launch, timerState, tz, setOverlay, tvControls: tc } = useApp()
  const { msg, run, verified } = useTimerActions()
  const [custom, setCustom] = useState(20)
  const [confirm, setConfirm] = useState(false)
  useLayer('quick', !confirm, onClose)
  const pinned = appsOf(snap)
  return (
    <div className="overlay"><div className="panel">
      <h2>Quick controls</h2>
      <div className="dim small">
        {timerState === 'unavailable' ? 'Timer status unavailable' : timerState.scheduled ? `Timer running` : 'No timer'}
        {!verified && ' · not yet verified on this TV'}
      </div>
      <div className="presets">
        {[15, 30, 45, 60, 90].map((m, i) => <Btn key={m} id={`q-${m}`} scope="quick" initial={i === 0} onClick={() => run((a) => a.schedule(m))}>{m} min</Btn>)}
      </div>
      <div className="stepper">
        <Btn id="q-minus" scope="quick" className="chip" onClick={() => setCustom((c) => Math.max(1, c - 5))}>−5</Btn>
        <b>{custom} min</b>
        <Btn id="q-plus" scope="quick" className="chip" onClick={() => setCustom((c) => Math.min(720, c + 5))}>+5</Btn>
        <Btn id="q-custom" scope="quick" onClick={() => run((a) => a.schedule(custom))}>Set custom</Btn>
        <Btn id="q-cancel" scope="quick" className="ghost" onClick={() => run((a) => a.cancel())}>Cancel timer</Btn>
      </div>
      <div className={`status-msg ${msg?.warn ? 'warn' : ''}`}>{msg?.text}</div>
      <div className="presets">
        <Btn id="q-sleepapp" scope="quick" className="ghost" onClick={() => void launch(SLEEP_APP, 'V/TV Sleep')}>Open V/TV Sleep</Btn>
        {pinned.slice(0, 3).map((a) => <Btn key={a.id} id={`q-app-${a.id}`} scope="quick" className="ghost" onClick={() => void launch(a.id, a.label)}>{a.label}</Btn>)}
        <Btn id="q-ambient" scope="quick" className="ghost" onClick={() => setOverlay('ambient')}>Photo frame</Btn>
        <Btn id="q-help" scope="quick" className="ghost" onClick={() => setOverlay('help')}>Help</Btn>
        <Btn id="q-guest" scope="quick" className={guest ? 'on' : 'ghost'} onClick={() => { setGuest(!guest); onClose() }}>{guest ? 'End guest view' : 'Guest view'}</Btn>
        <Btn id="q-off" scope="quick" className="ghost" onClick={() => setConfirm(true)}>TV off now</Btn>
      </div>
      {tc.volume.cap === 'supported' && <div className="stepper">
        <Btn id="q-vdown" scope="quick" className="chip" onClick={tc.volumeDown}>Vol −</Btn>
        <b>{tc.volume.volume ?? '–'}{tc.volume.muted ? ' · muted' : ''}</b>
        <Btn id="q-vup" scope="quick" className="chip" onClick={tc.volumeUp}>Vol +</Btn>
        <Btn id="q-mute" scope="quick" className={tc.volume.muted ? 'on' : 'ghost'} onClick={tc.toggleMute}>{tc.volume.muted ? 'Unmute' : 'Mute'}</Btn>
      </div>}
      {tc.picture.cap === 'supported' && <div className="presets">
        {PICTURE_MODES.map((m) => <Btn key={m} id={`q-pic-${m}`} scope="quick" className={tc.picture.mode === m ? 'on' : 'ghost'} onClick={() => tc.setPicture(m)}>{m[0].toUpperCase() + m.slice(1)}</Btn>)}
      </div>}
      <div className="dim small" data-tz={tz}>{tc.volume.cap === 'supported' || tc.picture.cap === 'supported' ? 'Picture mode and volume apply to the TV right now.' : 'Volume and picture appear here only if this TV allows V/HOME to control them (see Settings, Diagnostics).'}</div>
      {confirm && <ConfirmOff onClose={() => setConfirm(false)} />}
    </div></div>
  )
}
