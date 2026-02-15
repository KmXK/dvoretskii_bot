import { NavLink } from 'react-router-dom'

const links = [
  { to: '/', label: 'Home' },
  { to: '/charts', label: 'Charts' },
  { to: '/profile', label: 'Profile' },
  { to: '/casino', label: 'Casino' },
]

export default function NavBar() {
  return (
    <nav className="fixed bottom-0 left-0 right-0 z-50 bg-spotify-dark/95 backdrop-blur-md border-t border-white/5">
      <div className="flex justify-around items-center h-14 max-w-lg mx-auto px-2">
        {links.map(({ to, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `flex flex-col items-center gap-0.5 text-xs font-medium transition-colors px-3 py-1.5 rounded-lg ${
                isActive
                  ? 'text-spotify-green'
                  : 'text-spotify-text hover:text-white'
              }`
            }
          >
            {label}
          </NavLink>
        ))}
      </div>
    </nav>
  )
}
