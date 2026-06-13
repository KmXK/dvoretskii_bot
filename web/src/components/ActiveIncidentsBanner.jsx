import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useNavigate } from 'react-router-dom'
import { Siren, ChevronRight } from 'lucide-react'
import { api } from '../api/client'

export default function ActiveIncidentsBanner() {
  const [count, setCount] = useState(0)
  const navigate = useNavigate()

  useEffect(() => {
    let alive = true
    const load = () =>
      api.get('/api/incidents/active-count')
        .then((d) => { if (alive && d) setCount(d.count || 0) })
        .catch(() => {})
    load()
    const id = setInterval(load, 30_000)
    return () => { alive = false; clearInterval(id) }
  }, [])

  return (
    <AnimatePresence>
      {count > 0 && (
        <motion.button
          initial={{ opacity: 0, y: -8, scale: 0.96 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -8, scale: 0.96 }}
          transition={{ type: 'spring', stiffness: 280, damping: 22 }}
          onClick={() => navigate('/incidents')}
          className="w-full mb-4 px-4 py-3 rounded-2xl flex items-center gap-3
                     text-left shadow-lg border border-red-400/40
                     hover:scale-[1.01] active:scale-[0.99] transition-transform"
          style={{
            background: 'linear-gradient(135deg, #ff1744 0%, #d500f9 100%)',
          }}
        >
          <motion.span
            animate={{ scale: [1, 1.18, 1], rotate: [0, -8, 8, 0] }}
            transition={{ duration: 1.4, repeat: Infinity }}
            className="text-white"
          >
            <Siren size={24} strokeWidth={2.2} />
          </motion.span>
          <div className="flex-1 min-w-0">
            <div className="text-white font-bold text-sm drop-shadow">
              {count === 1 ? 'Активный инцидент' : `${count} активных инцидентов`}
            </div>
            <div className="text-white/85 text-xs mt-0.5">
              Тыкни чтобы посмотреть и закрыть
            </div>
          </div>
          <ChevronRight size={20} className="text-white/90" />
        </motion.button>
      )}
    </AnimatePresence>
  )
}
