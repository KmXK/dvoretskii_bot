import { motion } from 'framer-motion'
import { useNavigate } from 'react-router-dom'

export default function NotFoundPage() {
  const navigate = useNavigate()

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="px-4 pt-6 flex flex-col items-center justify-center min-h-[80vh] text-center"
    >
      <span className="text-7xl mb-4">⛷️</span>
      <h1 className="text-2xl font-bold text-white mb-2">404</h1>
      <p className="text-spotify-text text-lg mb-6">Ты куда забрался, горнолыжник?</p>
      <button
        onClick={() => navigate('/')}
        className="px-6 py-2.5 rounded-full bg-spotify-green text-black font-semibold text-sm"
      >
        На базу
      </button>
    </motion.div>
  )
}
