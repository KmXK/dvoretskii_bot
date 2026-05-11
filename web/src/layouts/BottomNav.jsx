import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import * as Dialog from '@radix-ui/react-dialog'
import { NAV_GROUPS } from './navigation'

const PRIMARY = [
  { to: '/', label: 'Главная', icon: '🏠' },
  { to: '/profile', label: 'Профиль', icon: '👤' },
  { to: '/casino', label: 'Казино', icon: '🎰' },
]

function NavItem({ to, icon, label }) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }) =>
        `flex flex-col items-center gap-0.5 px-3 py-1.5 rounded-lg text-[10px] font-medium transition-colors ${
          isActive ? 'text-spotify-green' : 'text-spotify-text hover:text-white'
        }`
      }
    >
      <span className="text-lg leading-none">{icon}</span>
      <span>{label}</span>
    </NavLink>
  )
}

export default function BottomNav() {
  const [menuOpen, setMenuOpen] = useState(false)

  return (
    <>
      <nav className="fixed bottom-0 left-0 right-0 z-40 bg-spotify-dark/95 backdrop-blur-md border-t border-white/5">
        <div className="flex justify-around items-center h-14 max-w-lg mx-auto px-2">
          {PRIMARY.map((p) => <NavItem key={p.to} {...p} />)}
          <button
            onClick={() => setMenuOpen(true)}
            className="flex flex-col items-center gap-0.5 px-3 py-1.5 rounded-lg text-[10px] font-medium text-spotify-text hover:text-white"
          >
            <span className="text-lg leading-none">≡</span>
            <span>Ещё</span>
          </button>
        </div>
      </nav>

      <Dialog.Root open={menuOpen} onOpenChange={setMenuOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm" />
          <Dialog.Content className="fixed inset-x-0 bottom-0 z-50 max-h-[80vh] overflow-y-auto bg-spotify-dark rounded-t-2xl shadow-2xl p-4 pb-8">
            <Dialog.Title className="text-white text-base font-semibold mb-4">Все разделы</Dialog.Title>
            <div className="space-y-5">
              {NAV_GROUPS.map((group) => (
                <div key={group.label}>
                  <div className="text-[10px] uppercase tracking-wider text-spotify-text/60 font-semibold mb-2">
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
                          `flex flex-col items-center justify-center gap-1 px-2 py-3 rounded-xl text-xs ${
                            isActive
                              ? 'bg-spotify-green/20 text-spotify-green'
                              : 'bg-white/5 text-white hover:bg-white/10'
                          }`
                        }
                      >
                        <span className="text-xl">{item.icon}</span>
                        <span className="leading-tight text-center">{item.label}</span>
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
