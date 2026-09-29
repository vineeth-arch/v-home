import { Header, Nav, OurHome, Watch, Us, Ideas, Apps, Settings, Pairing, PairingGate } from './screens'
import { useApp, type Screen } from './state'
import { useLayer } from './FocusProvider'
import { QuickControls } from './QuickControls'
import { MorningRitual, BedtimeRitual } from './rituals'
import { Ambient } from './Ambient'
import { Studio } from './Studio'

const TITLES: Record<Exclude<Screen, 'home'>, string> = { watch: 'Watch Together', us: 'Us', ideas: 'Idea Wall', apps: 'Apps', settings: 'Settings', studio: 'Studio' }

export function App() {
  const { screen, go, overlay, setOverlay, live, toast } = useApp()
  useLayer('nav:screen', screen !== 'home', () => go('home'))
  const close = () => setOverlay(null)
  if (live && live.status !== 'ready') return <PairingGate />
  return (
    <div className="app">
      <Header title={screen === 'home' ? undefined : TITLES[screen]} />
      <div key={screen} className="screen-in">
        {screen === 'home' && <OurHome />}
        {screen === 'watch' && <Watch />}
        {screen === 'us' && <Us />}
        {screen === 'ideas' && <Ideas />}
        {screen === 'apps' && <Apps />}
        {screen === 'settings' && <Settings />}
        {screen === 'studio' && <Studio />}
      </div>
      {live?.offline && <div className="offline">Showing saved content{live.snapshot ? ` from ${new Date(live.snapshot.syncedAt).toLocaleTimeString()}` : ''}. Reconnecting…</div>}
      {toast && <div className="toast" role="status">{toast}</div>}
      <Nav />
      {overlay === 'quick' && <QuickControls onClose={close} />}
      {overlay === 'morning' && <MorningRitual onClose={close} />}
      {overlay === 'bedtime' && <BedtimeRitual onClose={close} />}
      {overlay === 'pairing' && <Pairing onClose={close} />}
      {overlay === 'ambient' && <Ambient onClose={close} />}
    </div>
  )
}
