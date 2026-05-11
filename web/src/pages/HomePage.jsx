import { motion } from 'framer-motion'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/useAuth'
import { HOME_CARDS } from '../layouts/navigation'

export default function HomePage() {
  const navigate = useNavigate()
  const { username, firstName, mode } = useAuth()
  const greetName = firstName || username || 'друг'

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="px-4 pt-6 pb-6 max-w-6xl mx-auto"
    >
      <div className="mb-6">
        <h1 className="text-2xl md:text-3xl font-bold text-white mb-1 tracking-tight">
          Привет, {greetName}
        </h1>
        <p className="text-spotify-text text-sm">
          {mode === 'miniapp' ? 'Мини-приложение' : 'Веб-приложение'}
        </p>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        {HOME_CARDS.map((card, i) => (
          <motion.div
            key={card.title}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: Math.min(i * 0.05, 0.4), duration: 0.3 }}
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
