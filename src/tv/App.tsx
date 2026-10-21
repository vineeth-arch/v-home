import { Header, Nav, OurHome, Watch, Us, Ideas, Settings, Pairing, PairingGate } from './screens'
import { Btn } from './ui'
import { useApp, type Screen } from './state'
import { useLayer } from './FocusProvider'
import { QuickControls } from './QuickControls'
import { MorningRitual, BedtimeRitual } from './rituals'
import { Ambient } from './Ambient'
import { Studio } from './Studio'
import { Launcher } from './Launcher'
import { Help } from './Help'

const TITLES: Record<Exclude<Screen, 'home' | 'launcher'>, string> = { watch: 'Watch Together', us: 'Us', ideas: 'Idea Wall', settings: 'Settings', studio: 'Studio' }

const HOUSEHOLD: Screen[] = ['home', 'watch', 'us', 'ideas', 'studio']

/** Root Back lands here instead of closing at once, so a stray press does not drop the user out of V/HOME. */
function ExitDialog({ onClose }: { onClose: () => void }) {
  useLayer('exit', true, onClose)
  return <div className="overlay"><div className="panel exit-panel" role="dialog" aria-label="Leave V/HOME?">
    <h2>Leave V/HOME?</h2>
    <p className="dim">If the Mac helper is running, pressing Home brings V/HOME back. To use LG Home, pause the helper: <code>python -m vhome_companion pause</code></p>
    <div className="presets">
      <Btn id="exit-stay" scope="exit" initial className="primary" onClick={onClose}>Stay</Btn>
      <Btn id="exit-leave" scope="exit" className="ghost" onClick={() => window.close()}>Leave</Btn>
    </div>
  </div></div>
}

export function App() {
  const { screen, go, overlay, setOverlay, live, toast } = useApp()
  useLayer('nav:screen', screen !== 'launcher', () => go('launcher'))
  const close = () => setOverlay(null)
  const gated = !!live && live.status !== 'ready' && HOUSEHOLD.includes(screen)
  return (
    <div className="app">
      <Header title={screen === 'home' || screen === 'launcher' ? undefined : TITLES[screen]} />
      <div key={screen} className="screen-in">
        {gated && <PairingGate />}
        {!gated && screen === 'launcher' && <Launcher />}
        {!gated && screen === 'home' && <OurHome />}
        {!gated && screen === 'watch' && <Watch />}
        {!gated && screen === 'us' && <Us />}
        {!gated && screen === 'ideas' && <Ideas />}
        {screen === 'settings' && <Settings />}
        {!gated && screen === 'studio' && <Studio />}
      </div>
      {live?.offline && <div className="offline">Showing saved content{live.snapshot ? ` from ${new Date(live.snapshot.syncedAt).toLocaleTimeString()}` : ''}. Reconnecting…</div>}
      {toast && <div className="toast" role="status">{toast}</div>}
      <Nav />
      {overlay === 'quick' && <QuickControls onClose={close} />}
      {overlay === 'morning' && <MorningRitual onClose={close} />}
      {overlay === 'bedtime' && <BedtimeRitual onClose={close} />}
      {overlay === 'pairing' && <Pairing onClose={close} />}
      {overlay === 'ambient' && <Ambient onClose={close} />}
      {overlay === 'help' && <Help onClose={close} />}
      {overlay === 'exit' && <ExitDialog onClose={close} />}
    </div>
  )
}
