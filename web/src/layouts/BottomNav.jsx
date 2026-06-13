import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { motion } from 'framer-motion'
import * as Dialog from '@radix-ui/react-dialog'
import { Home, User, Dices, ChartColumn, Menu } from 'lucide-react'
import { NAV_GROUPS } from './navigation'
import ThemeToggle from '../components/ThemeToggle'

const PRIMARY = [
  { to: '/', label: 'Главная', Icon: Home },
  { to: '/profile', label: 'Профиль', Icon: User },
  { to: '/casino', label: 'Казино', Icon: Dices },
  { to: '/stats', label: 'Стата', Icon: ChartColumn },
]

function NavItem({ to, Icon, label }) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className="relative flex flex-1 flex-col items-center gap-1 pt-2 text-[10.5px] font-semibold"
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <motion.span
              layoutId="bottomnav-pill"
              transition={{ type: 'spring', stiffness: 500, damping: 32 }}
              className="absolute -top-px h-[3px] w-6 rounded-full bg-gold"
              style={{ boxShadow: '0 0 12px var(--color-gold)' }}
            />
          )}
          <span
            className={`grid h-8 w-8 place-items-center rounded-xl transition-colors ${
              isActive ? 'bg-gold-soft text-gold' : 'text-spotify-text'
            }`}
          >
            <Icon size={19} strokeWidth={2} />
          </span>
          <span className={isActive ? 'text-gold' : 'text-spotify-text'}>{label}</span>
        </>
      )}
    </NavLink>
  )
}

export default function BottomNav() {
  const [menuOpen, setMenuOpen] = useState(false)

  return (
    <>
      <nav
        className="fixed bottom-0 left-0 right-0 z-40 border-t border-white/5 bg-spotify-dark/85 backdrop-blur-xl"
        style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
      >
        <div className="mx-auto flex h-[68px] max-w-lg items-start justify-around px-3">
          {PRIMARY.map((p) => <NavItem key={p.to} {...p} />)}
          <button
            onClick={() => setMenuOpen(true)}
            className="relative flex flex-1 flex-col items-center gap-1 pt-2 text-[10.5px] font-semibold text-spotify-text"
          >
            <span className="grid h-8 w-8 place-items-center rounded-xl">
              <Menu size={19} strokeWidth={2} />
            </span>
            <span>Ещё</span>
          </button>
        </div>
      </nav>

      <Dialog.Root open={menuOpen} onOpenChange={setMenuOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm" />
          <Dialog.Content
            className="fixed inset-x-0 bottom-0 z-50 flex max-h-[85svh] flex-col rounded-t-2xl bg-spotify-dark shadow-2xl"
            style={{ paddingBottom: 'calc(env(safe-area-inset-bottom) + 12px)' }}
          >
            <div className="flex justify-center pt-2.5 pb-1">
              <div className="h-1 w-9 rounded-full bg-white/15" />
            </div>
            <div className="flex items-center justify-between px-4 pb-3">
              <Dialog.Title className="text-base font-semibold text-white">Все разделы</Dialog.Title>
              <ThemeToggle />
            </div>
            <div className="flex-1 overflow-y-auto px-4 pb-2 space-y-5 overscroll-contain">
              {NAV_GROUPS.map((group) => (
                <div key={group.label}>
                  <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-spotify-text/60">
                    {group.label}
                  </div>
                  <div className="grid grid-cols-3 gap-2">
                    {group.items.map((item) => (
                      <NavLink
                        key={item.to}
                        to={item.to}
                        end={item.to === '/'}
                        onClick={() => setMenuOpen(false)}
                        className={({ isActive }) =>
                          `flex flex-col items-center justify-center gap-1.5 rounded-xl px-2 py-3 text-xs transition-colors ${
                            isActive
                              ? 'bg-gold-soft text-gold'
                              : 'bg-white/5 text-white hover:bg-white/10'
                          }`
                        }
                      >
                        <item.Icon size={20} strokeWidth={2} />
                        <span className="text-center leading-tight">{item.label}</span>
                      </NavLink>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  )
}
