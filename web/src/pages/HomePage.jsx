import { motion } from 'framer-motion'
import { useNavigate } from 'react-router-dom'

const cards = [
  { title: 'Todo', desc: 'Список задач', emoji: '📝', color: 'from-rose-500/20 to-rose-900/20', to: '/todo' },
  { title: 'Army', desc: 'Статус по армейке', emoji: '🎖️', color: 'from-emerald-500/20 to-emerald-900/20', to: '/army' },
  { title: 'Features', desc: 'Фича-реквесты', emoji: '💡', color: 'from-cyan-500/20 to-cyan-900/20', to: '/features' },
]

export default function HomePage() {
  const navigate = useNavigate()

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="px-4 pt-6"
    >
      <h1 className="text-2xl font-bold text-white mb-1">Dvoretskiy</h1>
      <p className="text-spotify-text text-sm mb-6">Mini App</p>

      <div className="grid grid-cols-2 gap-3">
        {cards.map((card, i) => (
          <motion.div
            key={card.title}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.08, duration: 0.3 }}
            onClick={() => card.to && navigate(card.to)}
            className={`bg-gradient-to-br ${card.color} bg-spotify-gray rounded-xl p-4 cursor-pointer
              hover:scale-[1.03] active:scale-[0.98] transition-transform`}
          >
            <span className="text-3xl">{card.emoji}</span>
            <h3 className="text-white font-semibold mt-3 text-sm">{card.title}</h3>
            <p className="text-spotify-text text-xs mt-1">{card.desc}</p>
          </motion.div>
        ))}
      </div>

      <div className="mt-6 bg-spotify-dark rounded-xl p-4">
        <h2 className="text-white font-semibold mb-3">Recent Activity</h2>
        {['Alex earned 🏆 MVP', 'New bill: Pizza 🍕', 'Reminder: Meeting at 15:00'].map((item, i) => (
          <motion.div
            key={i}
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.5 + i * 0.1 }}
            className="flex items-center gap-3 py-2.5 border-b border-white/5 last:border-0"
          >
            <div className="w-2 h-2 rounded-full bg-spotify-green shrink-0" />
            <span className="text-spotify-text text-sm">{item}</span>
          </motion.div>
        ))}
      </div>
    </motion.div>
  )
}
