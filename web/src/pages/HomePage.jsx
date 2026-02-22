import { motion } from 'framer-motion'
import { useNavigate } from 'react-router-dom'

const cards = [
  { title: 'Todo', desc: 'Список задач', emoji: '📝', color: 'from-rose-500/20 to-rose-900/20', to: '/todo' },
  { title: 'Army', desc: 'Статус по армейке', emoji: '🎖️', color: 'from-emerald-500/20 to-emerald-900/20', to: '/army' },
  { title: 'Features', desc: 'Фича-реквесты', emoji: '💡', color: 'from-cyan-500/20 to-cyan-900/20', to: '/features' },
  { title: 'Tools', desc: 'Валюты, перевод, время', emoji: '🧰', color: 'from-amber-500/20 to-amber-900/20', to: '/tools' },
  { title: 'Reminders', desc: 'Напоминания', emoji: '🔔', color: 'from-blue-500/20 to-blue-900/20', to: '/reminders' },
  { title: 'Birthdays', desc: 'Дни рождения', emoji: '🎂', color: 'from-pink-500/20 to-pink-900/20', to: '/birthdays' },
  { title: 'Stats', desc: 'Статистика чатов', emoji: '📊', color: 'from-violet-500/20 to-violet-900/20', to: '/stats' },
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
    </motion.div>
  )
}
