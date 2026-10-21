// Launcher home (WS-C implements). Reads catalog/prefs from useApp(); never needs pairing or network.
import { useApp } from './state'

export function Launcher() {
  const { catalog } = useApp()
  return <div className="launcher" data-count={catalog.length} />
}
/** Settings section: appearance + layout editing entry point. */
export function LauncherSettings() { return null }
/** Settings section: catalog version/source, system apps, capability states. */
export function Diagnostics() { return null }
