import { useState } from 'react'
import { motion } from 'framer-motion'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/useAuth'
import { NAV_GROUPS } from '../layouts/navigation'
import ActiveIncidentsBanner from '../components/ActiveIncidentsBanner'

const TINTS = {
  gold: 'text-gold bg-gold-soft',
  indigo: 'text-indigo bg-indigo-soft',
  green: 'text-spotify-green bg-spotify-green/10',
  rose: 'text-rose-400 bg-rose-500/10',
  slate: 'text-spotify-text bg-white/5',
}

const HOME_SECTIONS = NAV_GROUPS
  .map((g) => ({ label: g.label, items: g.items.filter((i) => i.home) }))
  .filter((g) => g.items.length > 0)

function greeting() {
  const h = new Date().getHours()
  if (h < 6) return 'Доброй ночи'
  if (h < 12) return 'Доброе утро'
  if (h < 18) return 'Добрый день'
  return 'Добрый вечер'
}

function Avatar({ photoUrl, firstName, username }) {
  const [broken, setBroken] = useState(false)
  const initial = (firstName?.[0] || username?.[0] || '?').toUpperCase()
  return (
    <div className="grid h-14 w-14 shrink-0 place-items-center overflow-hidden rounded-2xl bg-gradient-to-br from-gold to-gold-2 text-xl font-extrabold text-black shadow-lg ring-1 ring-white/10">
      {photoUrl && !broken ? (
        <img src={photoUrl} alt="" className="h-full w-full object-cover" onError={() => setBroken(true)} />
      ) : (
        initial
      )}
    </div>
  )
}

export default function HomePage() {
  const navigate = useNavigate()
  const { username, firstName, photoUrl } = useAuth()
  const greetName = firstName || username || 'друг'

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="mx-auto max-w-6xl px-4 pb-6 pt-6"
    >
      <div className="relative mb-6 overflow-hidden rounded-3xl border border-white/5 bg-gradient-to-br from-gold-soft via-indigo-soft to-transparent p-5">
        <div className="pointer-events-none absolute -right-16 -top-24 h-56 w-56 rounded-full bg-gold/25 blur-2xl" />
        <div className="relative flex items-center gap-4">
          <Avatar photoUrl={photoUrl} firstName={firstName} username={username} />
          <div className="min-w-0">
            <p className="text-sm font-medium text-spotify-text">{greeting()}</p>
            <h1 className="truncate text-2xl font-extrabold tracking-tight text-white">{greetName}</h1>
            <span className="mt-2 inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] font-semibold text-spotify-text">
              <span className="h-1.5 w-1.5 rounded-full bg-spotify-green shadow-[0_0_8px_var(--color-spotify-green)]" />
              дворецкий на связи
            </span>
          </div>
        </div>
      </div>

      <ActiveIncidentsBanner />

      <div className="space-y-6">
        {HOME_SECTIONS.map((section, si) => (
          <section key={section.label}>
            <h2 className="mb-3 ml-1 text-xs font-bold uppercase tracking-[0.08em] text-spotify-text">
              {section.label}
            </h2>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
              {section.items.map((item, i) => (
                <motion.button
                  key={item.to}
                  initial={{ opacity: 0, y: 16 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: Math.min((si * 0.04) + i * 0.03, 0.4), duration: 0.3 }}
                  whileTap={{ scale: 0.97 }}
                  onClick={() => navigate(item.to)}
                  className="group flex flex-col items-start rounded-2xl border border-white/5 bg-spotify-gray p-4 text-left shadow-sm transition-colors hover:border-white/10 hover:bg-spotify-light-gray/40"
                >
                  <span className={`grid h-11 w-11 place-items-center rounded-xl ${TINTS[item.home.tint] || TINTS.slate}`}>
                    <item.Icon size={22} strokeWidth={2} />
                  </span>
                  <h3 className="mt-3 text-sm font-bold text-white">{item.home.title ?? item.label}</h3>
                  <p className="mt-0.5 text-xs text-spotify-text">{item.home.desc}</p>
                </motion.button>
              ))}
            </div>
          </section>
        ))}
      </div>
    </motion.div>
  )
}
