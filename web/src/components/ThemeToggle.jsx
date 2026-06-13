import { motion, AnimatePresence } from 'framer-motion'
import { Sun, Moon } from 'lucide-react'
import { useTheme } from '../context/useTheme'

export default function ThemeToggle({ className = '' }) {
  const { theme, toggle } = useTheme()
  const isLight = theme === 'light'

  return (
    <motion.button
      whileTap={{ scale: 0.85, rotate: -15 }}
      onClick={toggle}
      className={`p-1.5 rounded-md text-spotify-text hover:text-white hover:bg-white/5 transition-colors ${className}`}
      title={isLight ? 'Тёмная тема' : 'Светлая тема'}
      aria-label="Переключить тему"
    >
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.span
          key={theme}
          initial={{ rotate: -90, opacity: 0, scale: 0.5 }}
          animate={{ rotate: 0, opacity: 1, scale: 1 }}
          exit={{ rotate: 90, opacity: 0, scale: 0.5 }}
          transition={{ type: 'spring', stiffness: 400, damping: 20 }}
          className="block leading-none"
        >
          {isLight ? <Sun size={17} /> : <Moon size={17} />}
        </motion.span>
      </AnimatePresence>
    </motion.button>
  )
}
