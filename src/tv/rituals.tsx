import { useState } from 'react'
import { Btn, DreamArt } from './ui'
import { useLayer } from './FocusProvider'
import { useApp, personName } from './state'
import { useTimerActions } from './timerActions'
import { pickDaily } from '../shared/reflections'
import { localDate } from '../shared/daily'
import { ConfirmOff } from './QuickControls'

/** Manually advanced cards. No required input, streaks, or completion pressure. */
function Flow({ scope, cards, onClose, start = 0 }: { scope: string; cards: { step: string; body: React.ReactNode }[]; onClose: () => void; start?: number }) {
  const [i, setI] = useState(start)
  useLayer(scope, true, onClose)
  const last = i === cards.length - 1
  return (
    <div className="overlay"><div className="panel card-flow">
      <div className="step">{cards[i].step} · {i + 1} of {cards.length}</div>
      <div key={i} className="card-in">{cards[i].body}</div>
      <div className="flow-nav">
        {i > 0 && <Btn id={`${scope}-prev`} scope={scope} className="ghost" onClick={() => setI(i - 1)}>Previous</Btn>}
        {!last && <Btn id={`${scope}-next`} scope={scope} initial className="primary" onClick={() => setI(i + 1)}>Next</Btn>}
        <Btn id={`${scope}-close`} scope={scope} initial={last} className={last ? 'primary' : 'ghost'} onClick={onClose}>{last ? 'Done' : 'Skip the rest'}</Btn>
      </div>
    </div></div>
  )
}

export function MorningRitual({ onClose, startAt = 0 }: { onClose: () => void; startAt?: number }) {
  const { snap, now, tz } = useApp()
  const dream = snap.dreams[0]
  const r = pickDaily(snap.household.id || snap.household.name, localDate(now, tz), 'morning', snap.household.hiddenReflections, snap.quotes)
  const [step, setStep] = useState<string | null>(null)
  const [who, setWho] = useState<string>('both')
  const whos = ['both', ...snap.household.people.map((p) => p.id)]
  const steps = [dream?.nextStep, ...snap.tasks.filter((t) => !t.done && t.kind === 'task').slice(0, 2).map((t) => t.title)].filter(Boolean) as string[]
  return <Flow scope="ritual" onClose={onClose} start={startAt} cards={[
    { step: 'Imagine', body: dream ? <><div className="art"><DreamArt kind={dream.art} /></div><div className="big">{dream.title}</div><div className="dim">{dream.why}</div></> : <div className="big">What would a good day feel like?</div> },
    { step: 'Intend', body: <><div className="big">{dream?.affirmation ?? r?.text}</div><div className="dim">Take a moment to name one thing you are grateful for. Say it out loud if you like.</div></> },
    { step: 'Act', body: <>
      <div className="big">What small step moves us toward this today?</div>
      <div className="presets" style={{ justifyContent: 'center' }}>{steps.map((s, k) => <Btn key={s} id={`step-${k}`} scope="ritual" className={step === s ? 'on' : 'ghost'} onClick={() => setStep(s)}>{s}</Btn>)}</div>
      {step && <div className="presets" style={{ justifyContent: 'center' }}><span className="dim">Who?</span>{whos.map((w) => <Btn key={w} id={`who-${w}`} scope="ritual" className={`chip ${who === w ? 'on' : 'ghost'}`} onClick={() => setWho(w)}>{personName(snap, w)}</Btn>)}</div>}
      {step && <div className="status-msg">Today's step: {step} · {personName(snap, who)}</div>}
    </> },
  ]} />
}

export function BedtimeRitual({ onClose }: { onClose: () => void }) {
  const { snap, now, tz } = useApp()
  const dream = snap.dreams[0]
  const r = pickDaily(snap.household.id || snap.household.name, localDate(now, tz), 'evening', snap.household.hiddenReflections, snap.quotes)
  const { msg, run } = useTimerActions()
  const [off, setOff] = useState(false)
  return <>
    <Flow scope="ritual" onClose={onClose} cards={[
      { step: 'Appreciate', body: <div className="big">What was one good thing about today?</div> },
      { step: 'Connect', body: <><div className="big">Tell each other one thing you appreciate.</div><div className="dim">Or simply share how the day felt.</div></> },
      { step: 'Imagine', body: <>{dream && <div className="art"><DreamArt kind={dream.art} /></div>}<div className="big">{r?.text}</div></> },
      { step: 'Rest', body: <>
        <div className="big">Ready to rest?</div>
        <div className="presets" style={{ justifyContent: 'center' }}>
          {[30, 45, 60].map((m) => <Btn key={m} id={`rest-${m}`} scope="ritual" className="ghost" onClick={() => run((a) => a.schedule(m))}>Sleep in {m} min</Btn>)}
          <Btn id="rest-off" scope="ritual" className="ghost" onClick={() => setOff(true)}>TV off now</Btn>
        </div>
        <div className={`status-msg ${msg?.warn ? 'warn' : ''}`}>{msg?.text}</div>
      </> },
    ]} />
    {off && <ConfirmOff onClose={() => setOff(false)} />}
  </>
}
