import { Header, Nav, OurHome, Watch, Us, Ideas, Settings, Pairing } from './screens'
import { useApp, type Screen } from './state'
import { useLayer } from './FocusProvider'
import { QuickControls } from './QuickControls'
import { MorningRitual, BedtimeRitual } from './rituals'

const TITLES: Record<Exclude<Screen, 'home'>, string> = { watch: 'Watch Together', us: 'Us', ideas: 'Idea Wall', settings: 'Settings' }

export function App() {
  const { screen, go, overlay, setOverlay } = useApp()
  useLayer('nav:screen', screen !== 'home', () => go('home'))
  const close = () => setOverlay(null)
  return (
    <div className="app">
      <Header title={screen === 'home' ? undefined : TITLES[screen]} />
      <div key={screen} className="screen-in">
        {screen === 'home' && <OurHome />}
        {screen === 'watch' && <Watch />}
        {screen === 'us' && <Us />}
        {screen === 'ideas' && <Ideas />}
        {screen === 'settings' && <Settings />}
      </div>
      <Nav />
      {overlay === 'quick' && <QuickControls onClose={close} />}
      {overlay === 'morning' && <MorningRitual onClose={close} />}
      {overlay === 'bedtime' && <BedtimeRitual onClose={close} />}
      {overlay === 'pairing' && <Pairing onClose={close} />}
    </div>
  )
}
