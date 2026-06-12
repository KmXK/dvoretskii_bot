import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'

const STORAGE_KEY = 'light_theme_joke_v1'

function alreadyShown() {
  try {
    return localStorage.getItem(STORAGE_KEY) === '1'
  } catch {
    return true
  }
}

export default function LightThemeJoke() {
  const [open, setOpen] = useState(() => !alreadyShown())

  const close = () => {
    try {
      localStorage.setItem(STORAGE_KEY, '1')
    } catch { /* noop */ }
    setOpen(false)
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-[100] flex items-center justify-center px-6 bg-black/70 backdrop-blur-sm"
        >
          <motion.div
            initial={{ scale: 0.8, y: 30, opacity: 0 }}
            animate={{ scale: 1, y: 0, opacity: 1 }}
            exit={{ scale: 0.9, y: 10, opacity: 0 }}
            transition={{ type: 'spring', stiffness: 400, damping: 26 }}
            className="bg-spotify-dark rounded-2xl p-6 max-w-sm w-full text-center shadow-2xl border border-white/10"
          >
            <motion.span
              className="text-4xl block mb-3"
              animate={{ rotate: [0, -6, 6, 0] }}
              transition={{ duration: 1.8, repeat: Infinity, repeatDelay: 0.8 }}
            >
              🌚
            </motion.span>
            <p className="text-white text-sm leading-relaxed mb-5">
              Если любишь светлую тему то убейся потому что ее не будет
            </p>
            <motion.button
              whileTap={{ scale: 0.93 }}
              onClick={close}
              className="bg-spotify-green text-black text-sm font-semibold px-8 py-2.5 rounded-full"
            >
              Ок
            </motion.button>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
