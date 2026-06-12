import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { useAuth } from '../context/useAuth'
import { NAV_GROUPS } from './navigation'
import ThemeToggle from '../components/ThemeToggle'

function NavItem({ item, collapsed }) {
  return (
    <NavLink
      to={item.to}
      end={item.to === '/'}
      className={({ isActive }) =>
        `group relative flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
          isActive
            ? 'bg-white/10 text-white'
            : 'text-spotify-text hover:text-white hover:bg-white/5'
        } ${collapsed ? 'justify-center' : ''}`
      }
      title={collapsed ? item.label : undefined}
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <span className="absolute left-0 top-1.5 bottom-1.5 w-0.5 rounded-r bg-spotify-green" />
          )}
          <span className="text-lg shrink-0">{item.icon}</span>
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
        className={`${dim} rounded-full object-cover shrink-0 ring-1 ring-white/10`}
      />
    )
  }
  return (
    <div className={`${dim} rounded-full bg-gradient-to-br from-spotify-green to-emerald-700 flex items-center justify-center font-semibold text-white shrink-0 ring-1 ring-white/10`}>
      {initial}
    </div>
  )
}

export default function Sidebar({ open, onToggle, isDrawer = false, onClose }) {
  const collapsed = !open && !isDrawer
  const { me, username, firstName, photoUrl, logout } = useAuth()

  return (
    <aside
      className={`flex flex-col bg-spotify-dark border-r border-white/5 transition-[width] duration-200 h-screen ${
        isDrawer ? 'w-64' : collapsed ? 'w-16' : 'w-60'
      }`}
    >
      <div className={`flex items-center h-14 border-b border-white/5 ${collapsed ? 'justify-center' : 'justify-between px-3'}`}>
        {!collapsed && (
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-xl">🤖</span>
            <span className="text-white font-semibold tracking-tight truncate">Dvoretskiy</span>
          </div>
        )}
        {!collapsed && <ThemeToggle className="ml-auto" />}
        <button
          onClick={isDrawer ? onClose : onToggle}
          className="p-1.5 rounded-md text-spotify-text hover:text-white hover:bg-white/5 transition-colors"
          title={isDrawer ? 'Закрыть' : collapsed ? 'Развернуть' : 'Свернуть'}
        >
          <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            {isDrawer
              ? <path d="M6 18L18 6M6 6l12 12" />
              : collapsed
                ? <path d="M9 18l6-6-6-6" />
                : <path d="M15 18l-6-6 6-6" />}
          </svg>
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto py-3">
        {NAV_GROUPS.map((group, gi) => (
          <div key={group.label} className={`${gi === 0 ? '' : 'mt-3 pt-3 border-t border-white/5'} mb-1`}>
            {!collapsed && (
              <div className="px-3 mb-1 text-[10px] uppercase tracking-wider text-spotify-text/50 font-semibold">
                {group.label}
              </div>
            )}
            <div className="px-2 space-y-0.5">
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
            className="p-2 rounded-md text-spotify-text hover:text-white hover:bg-white/5 transition-colors"
            title={`${username ? '@' + username : 'Выйти'}`}
          >
            <Avatar photoUrl={photoUrl} username={username} firstName={firstName} me={me} size="sm" />
          </button>
        ) : (
          <div className="flex items-center gap-2 min-w-0">
            <Avatar photoUrl={photoUrl} username={username} firstName={firstName} me={me} size="sm" />
            <div className="min-w-0 flex-1">
              <div className="text-white text-sm truncate font-medium">
                {username ? `@${username}` : me ? `id:${me.user_id}` : ''}
              </div>
              {me?.is_admin && (
                <div className="text-amber-300 text-[10px] font-medium leading-tight">admin</div>
              )}
            </div>
            <button
              onClick={logout}
              className="p-1.5 text-spotify-text hover:text-white rounded hover:bg-white/5 transition-colors shrink-0"
              title="Выйти"
            >
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />
              </svg>
            </button>
          </div>
        )}
      </div>
    </aside>
  )
}
