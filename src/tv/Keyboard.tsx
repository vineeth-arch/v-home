// On-screen keyboard driven by the remote: arrows move over the keys, OK types, Back cancels.
import { useState } from 'react'
import { useFocusable, useLayer } from './FocusProvider'

const ROWS = ['ABCDEFGHI', 'JKLMNOPQR', 'STUVWXYZ-', '1234567890']
const SCOPE = 'kbd'

function Key({ id, className = '', initial, onClick, children }: { id: string; className?: string; initial?: boolean; onClick: () => void; children: React.ReactNode }) {
  const { className: fc, ...fp } = useFocusable(id, { scope: SCOPE, initial })
  return <button {...fp} className={`${fc} l-key ${className}`} onClick={onClick}>{children}</button>
}

/** Next character's case: capital at the start and after a space, lower case otherwise. */
export const caseFor = (text: string, ch: string) => (text === '' || text.endsWith(' ') ? ch.toUpperCase() : ch.toLowerCase())

export function OnScreenKeyboard({ title, initial = '', max = 24, onDone, onCancel }: { title: string; initial?: string; max?: number; onDone: (text: string) => void; onCancel: () => void }) {
  const [text, setText] = useState(initial.slice(0, max))
  useLayer(SCOPE, true, onCancel)
  const add = (ch: string) => setText((t) => (t.length >= max ? t : t + caseFor(t, ch)))
  return <div className="overlay l-edit l-kbd"><div className="panel">
    <h2>{title}</h2>
    <div className="l-kbd-text" role="status">{text || ' '}<span className="l-caret" /></div>
    <div className="l-kbd-rows">
      {ROWS.map((r, ri) => <div className="l-kbd-row" key={r}>{[...r].map((c, ci) => <Key key={c} id={`kb-${c}`} initial={ri === 0 && ci === 0} onClick={() => add(c)}>{c}</Key>)}</div>)}
      <div className="l-kbd-row">
        <Key id="kb-space" className="wide" onClick={() => setText((t) => (t.length >= max || t === '' ? t : t + ' '))}>Space</Key>
        <Key id="kb-del" className="wide" onClick={() => setText((t) => t.slice(0, -1))}>Delete</Key>
        <Key id="kb-clear" className="wide" onClick={() => setText('')}>Clear</Key>
        <Key id="kb-cancel" className="wide" onClick={onCancel}>Cancel</Key>
        <Key id="kb-done" className="wide primary" onClick={() => onDone(text.trim())}>Done</Key>
      </div>
    </div>
  </div></div>
}
