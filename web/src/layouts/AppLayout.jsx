import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useLocation } from 'react-router-dom'
import { Bot, Menu } from 'lucide-react'
import { useAuth } from '../context/useAuth'
import Sidebar from './Sidebar'
import BottomNav from './BottomNav'
import { useSidebar } from './useSidebar'
import ThemeToggle from '../components/ThemeToggle'
import { useTelegramBackButton } from '../hooks/useTelegramBackButton'

function TelegramBackButton() {
  useTelegramBackButton()
  return null
}

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
  const location = useLocation()

  useEffect(() => {
    setDrawerOpen(false)
  }, [location.pathname])

  if (mode === 'miniapp') {
    return (
      <div className="min-h-screen bg-spotify-black pb-24">
        <TelegramBackButton />
        {children}
        <BottomNav />
      </div>
    )
  }

  if (isWide) {
    return (
      <div className="flex min-h-screen bg-spotify-black">
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
          <Menu size={20} />
        </button>
        <div className="ml-3 flex items-center gap-2 flex-1 min-w-0">
          <Bot size={20} className="text-gold" />
          <span className="text-white font-semibold">Dvoretskiy</span>
        </div>
        <ThemeToggle />
      </header>

      <AnimatePresence>
        {drawerOpen && (
          <motion.div
            initial={{ x: '-100%' }}
            animate={{ x: 0 }}
            exit={{ x: '-100%' }}
            transition={{ type: 'spring', stiffness: 400, damping: 38 }}
            className="fixed inset-0 z-40"
          >
            <Sidebar isDrawer onClose={() => setDrawerOpen(false)} />
          </motion.div>
        )}
      </AnimatePresence>

      <main>{children}</main>
    </div>
  )
}
