import { useEffect, useState } from 'react'
import { useFocusable, useFocusCtx, useLayer } from './FocusProvider'
import { HELP } from './helpText'

const SCOPE = 'help'

function Topic({ id, active, initial, onPick, children }: { id: string; active: boolean; initial?: boolean; onPick: () => void; children: React.ReactNode }) {
  const { className: fc, ...fp } = useFocusable(id, { scope: SCOPE, initial })
  return <button {...fp} className={`${fc} l-btn l-topic${active ? ' on' : ''}`} onClick={onPick}>{children}</button>
}

export function Help({ onClose }: { onClose: () => void }) {
  const [i, setI] = useState(0)
  const { focusedId } = useFocusCtx()
  useEffect(() => { const k = HELP.findIndex((h) => `help-${h.id}` === focusedId); if (k >= 0) setI(k) }, [focusedId]) // the text follows the highlight
  useLayer(SCOPE, true, onClose)
  const t = HELP[i]
  return <div className="overlay l-edit l-help"><div className="panel">
    <div className="l-edit-top"><h2>Help</h2><span className="l-dim">Back to close</span></div>
    <div className="l-help-body">
      <nav className="l-help-list">{HELP.map((h, k) => <Topic key={h.id} id={`help-${h.id}`} active={k === i} initial={k === 0} onPick={() => setI(k)}>{h.title}</Topic>)}</nav>
      <article className="l-help-text"><h3>{t.title}</h3>{t.lines.map((l) => <p key={l}>{l}</p>)}</article>
    </div>
  </div></div>
}
