import { createRoot } from 'react-dom/client'
import '../styles/tokens.css'
import './stage.css'
import { FocusProvider, useFocusable } from './FocusProvider'
import { Stage } from './Stage'
import { createPlatform } from '../adapters/platform'

const platform = createPlatform()

function Demo() {
  const a = useFocusable('a'), b = useFocusable('b')
  return (
    <>
      <h1 style={{ fontSize: 'var(--fs-h1)', margin: 0 }}>V/HOME</h1>
      <div style={{ display: 'flex', gap: 48, marginTop: 48 }}>
        <button {...a} style={{ font: 'inherit', padding: '24px 48px' }}>One</button>
        <button {...b} style={{ font: 'inherit', padding: '24px 48px' }}>Two</button>
      </div>
    </>
  )
}

createRoot(document.getElementById('root')!).render(
  <FocusProvider><Stage simulated={platform.simulated}><Demo /></Stage></FocusProvider>,
)
