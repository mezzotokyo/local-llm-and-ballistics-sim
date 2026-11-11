import { useState } from 'react'
import { BallisticView } from './views/BallisticView'
import { OrbitalView } from './views/OrbitalView'
import './App.css'

type Mode = 'ballistic' | 'orbital'

export default function App() {
  const [mode, setMode] = useState<Mode>('ballistic')

  return (
    <main className="app">
      <header className="header">
        <h1>Range Calculator Web</h1>
        <p className="subtitle">
          弾道と軌道をそれぞれのビューで可視化します（RK4・適応刻み）。
        </p>
      </header>

      <nav className="tabs" role="tablist" aria-label="simulation mode">
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'ballistic'}
          className={mode === 'ballistic' ? 'tab active' : 'tab'}
          onClick={() => setMode('ballistic')}
        >
          弾道 (Ballistic)
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'orbital'}
          className={mode === 'orbital' ? 'tab active' : 'tab'}
          onClick={() => setMode('orbital')}
        >
          軌道 (Orbital)
        </button>
      </nav>

      {mode === 'ballistic' ? <BallisticView /> : <OrbitalView />}
    </main>
  )
}
