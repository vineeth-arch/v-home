import { useEffect, useState, type ReactNode } from 'react'

const W = 1920, H = 1080
/** 1920x1080 canvas. Scales to fit only in a desktop browser; on the TV (PalmSystem present) scale is 1. */
export function Stage({ children, simulated }: { children: ReactNode; simulated: boolean }) {
  const [scale, setScale] = useState(1)
  useEffect(() => {
    if (window.PalmSystem) return
    const fit = () => setScale(Math.min(innerWidth / W, innerHeight / H))
    fit(); addEventListener('resize', fit); return () => removeEventListener('resize', fit)
  }, [])
  return (
    <div className="stage-host">
      <div id="stage" style={{ width: W, height: H, transform: `translate(-50%, -50%) scale(${scale})` }}>
        {children}
        {simulated && <div className="sim-chip">SIMULATION</div>}
      </div>
    </div>
  )
}
