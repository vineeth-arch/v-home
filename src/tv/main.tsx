import { createRoot } from 'react-dom/client'
import '../styles/tokens.css'
import './stage.css'
import './ui.css'
import { FocusProvider } from './FocusProvider'
import { Stage } from './Stage'
import { AppProvider, useApp } from './state'
import { App } from './App'

function Root() {
  const { platform } = useApp()
  return <Stage simulated={platform.simulated}><App /></Stage>
}
createRoot(document.getElementById('root')!).render(<FocusProvider><AppProvider><Root /></AppProvider></FocusProvider>)
