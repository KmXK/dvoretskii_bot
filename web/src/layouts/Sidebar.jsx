import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { Bot, LogOut, ChevronLeft, ChevronRight, X } from 'lucide-react'
import { useAuth } from '../context/useAuth'
import { NAV_GROUPS } from './navigation'
import ThemeToggle from '../components/ThemeToggle'

function NavItem({ item, collapsed }) {
  return (
    <NavLink
      to={item.to}
      end={item.to === '/'}
      className={({ isActive }) =>
        `group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
          isActive
            ? 'bg-gold-soft text-gold'
            : 'text-spotify-text hover:bg-white/5 hover:text-white'
        } ${collapsed ? 'justify-center' : ''}`
      }
      title={collapsed ? item.label : undefined}
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <span className="absolute left-0 top-1.5 bottom-1.5 w-0.5 rounded-r bg-gold" />
          )}
          <item.Icon size={18} strokeWidth={2} className="shrink-0" />
          {!collapsed && <span className="truncate">{item.label}</span>}
        </>
      )}
    </NavLink>
  )
}

function Avatar({ photoUrl, username, firstName, me, size = 'sm' }) {
  const dim = size === 'sm' ? 'w-8 h-8 text-sm' : 'w-10 h-10 text-base'
  const [broken, setBroken] = useState(false)
  const initial = (firstName?.[0] || username?.[0] || me?.user_id?.toString()?.[0] || '?').toUpperCase()
  if (photoUrl && !broken) {
    return (
      <img
        src={photoUrl}
        alt=""
        onError={() => setBroken(true)}
        className={`${dim} shrink-0 rounded-full object-cover ring-1 ring-white/10`}
      />
    )
  }
  return (
    <div className={`${dim} flex shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-gold to-gold-2 font-semibold text-black ring-1 ring-white/10`}>
      {initial}
    </div>
  )
}

export default function Sidebar({ open, onToggle, isDrawer = false, onClose }) {
  const collapsed = !open && !isDrawer
  const { me, username, firstName, photoUrl, logout } = useAuth()

  return (
    <aside
      className={`flex h-screen flex-col border-r border-white/5 bg-spotify-dark transition-[width] duration-200 ${
        isDrawer ? 'w-full' : collapsed ? 'w-16' : 'w-60'
      }`}
    >
      <div className={`flex h-14 items-center border-b border-white/5 ${collapsed ? 'justify-center' : 'justify-between px-3'}`}>
        {!collapsed && (
          <div className="flex min-w-0 items-center gap-2">
            <Bot size={22} className="text-gold" />
            <span className="truncate font-semibold tracking-tight text-white">Dvoretskiy</span>
          </div>
        )}
        {!collapsed && <ThemeToggle className="ml-auto" />}
        <button
          onClick={isDrawer ? onClose : onToggle}
          className="rounded-md p-1.5 text-spotify-text transition-colors hover:bg-white/5 hover:text-white"
          title={isDrawer ? 'Закрыть' : collapsed ? 'Развернуть' : 'Свернуть'}
        >
          {isDrawer ? <X size={20} /> : collapsed ? <ChevronRight size={20} /> : <ChevronLeft size={20} />}
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto py-3">
        {NAV_GROUPS.map((group, gi) => (
          <div key={group.label} className={`${gi === 0 ? '' : 'mt-3 border-t border-white/5 pt-3'} mb-1`}>
            {!collapsed && (
              <div className="mb-1 px-3 text-[10px] font-semibold uppercase tracking-wider text-spotify-text/50">
                {group.label}
              </div>
            )}
            <div className="space-y-0.5 px-2">
              {group.items.map((item) => (
                <NavItem key={item.to} item={item} collapsed={collapsed} />
              ))}
            </div>
          </div>
        ))}
      </nav>

      <div className={`border-t border-white/5 p-3 ${collapsed ? 'flex justify-center' : ''}`}>
        {collapsed ? (
          <button
            onClick={logout}
            className="rounded-md p-2 text-spotify-text transition-colors hover:bg-white/5 hover:text-white"
            title={`${username ? '@' + username : 'Выйти'}`}
          >
            <Avatar photoUrl={photoUrl} username={username} firstName={firstName} me={me} size="sm" />
          </button>
        ) : (
          <div className="flex min-w-0 items-center gap-2">
            <Avatar photoUrl={photoUrl} username={username} firstName={firstName} me={me} size="sm" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium text-white">
                {username ? `@${username}` : me ? `id:${me.user_id}` : ''}
              </div>
              {me?.is_admin && (
                <div className="text-[10px] font-medium leading-tight text-amber-300">admin</div>
              )}
            </div>
            <button
              onClick={logout}
              className="shrink-0 rounded p-1.5 text-spotify-text transition-colors hover:bg-white/5 hover:text-white"
              title="Выйти"
            >
              <LogOut size={16} />
            </button>
          </div>
        )}
      </div>
    </aside>
  )
}
