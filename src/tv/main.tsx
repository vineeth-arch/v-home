import { Component, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import '../styles/tokens.css'
import './stage.css'
import './ui.css'
import { FocusProvider } from './FocusProvider'
import { Stage } from './Stage'
import { AppProvider, useApp } from './state'
import { App } from './App'

/** Safety net: a render crash must never leave the TV blank. Clear cached data once and reload; then show a message. */
class Boundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidCatch() {
    try {
      if (!sessionStorage.getItem('vhome.recovered')) {
        sessionStorage.setItem('vhome.recovered', '1')
        for (const k of Object.keys(localStorage)) if (k.startsWith('vhome.')) localStorage.removeItem(k)
        indexedDB.deleteDatabase('vhome')
        setTimeout(() => location.reload(), 500)
      }
    } catch { /* storage unavailable */ }
  }
  render() {
    return this.state.failed ? <div style={{ color: '#f5efe6', fontSize: 40, padding: 96, fontFamily: 'sans-serif' }}>V/HOME hit a problem and is restarting. If this stays, close and reopen the app.</div> : this.props.children
  }
}

function Root() {
  const { platform } = useApp()
  return <Stage simulated={platform.simulated}><App /></Stage>
}
createRoot(document.getElementById('root')!).render(<Boundary><FocusProvider><AppProvider><Root /></AppProvider></FocusProvider></Boundary>)
