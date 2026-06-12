import { useEffect, useState } from 'react'
import { useAuth } from '../context/useAuth'
import Sidebar from './Sidebar'
import BottomNav from './BottomNav'
import { useSidebar } from './useSidebar'
import ThemeToggle from '../components/ThemeToggle'
import LightThemeJoke from '../components/LightThemeJoke'

function useIsWide(breakpoint = 768) {
  const [wide, setWide] = useState(() =>
    typeof window === 'undefined' ? true : window.innerWidth >= breakpoint
  )
  useEffect(() => {
    if (typeof window === 'undefined') return
    const onResize = () => setWide(window.innerWidth >= breakpoint)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [breakpoint])
  return wide
}

export default function AppLayout({ children }) {
  const { mode } = useAuth()
  const isWide = useIsWide()
  const [open, toggle] = useSidebar()
  const [drawerOpen, setDrawerOpen] = useState(false)

  if (mode === 'miniapp') {
    return (
      <div className="min-h-screen bg-spotify-black pb-16">
        <LightThemeJoke />
        {children}
        <BottomNav />
      </div>
    )
  }

  if (isWide) {
    return (
      <div className="flex min-h-screen bg-spotify-black">
        <LightThemeJoke />
        <div className="sticky top-0 self-start">
          <Sidebar open={open} onToggle={toggle} />
        </div>
        <main className="flex-1 min-w-0">
          <div className="max-w-6xl mx-auto">{children}</div>
        </main>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-spotify-black">
      <header className="sticky top-0 z-30 flex items-center h-12 px-3 bg-spotify-dark/95 backdrop-blur-md border-b border-white/5">
        <button
          onClick={() => setDrawerOpen(true)}
          className="p-1.5 rounded-md text-spotify-text hover:text-white hover:bg-white/5"
          aria-label="Открыть меню"
        >
          <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 6h18M3 12h18M3 18h18" />
          </svg>
        </button>
        <div className="ml-3 flex items-center gap-2 flex-1 min-w-0">
          <span className="text-lg">🤖</span>
          <span className="text-white font-semibold">Dvoretskiy</span>
        </div>
        <ThemeToggle />
      </header>
      <LightThemeJoke />

      {drawerOpen && (
        <div className="fixed inset-0 z-40 flex">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => setDrawerOpen(false)}
          />
          <div className="relative z-10">
            <Sidebar isDrawer onClose={() => setDrawerOpen(false)} />
          </div>
        </div>
      )}

      <main>{children}</main>
    </div>
  )
}
