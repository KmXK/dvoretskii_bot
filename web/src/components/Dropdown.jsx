import { useState, useEffect, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'

export default function Dropdown({ value, onChange, options, placeholder, className = '', compact = false }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const current = options.find(f => String(f.value) === String(value))

  useEffect(() => {
    if (!open) return
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('pointerdown', handler)
    return () => document.removeEventListener('pointerdown', handler)
  }, [open])

  return (
    <div ref={ref} className={`relative ${className}`}>
      <button
        onClick={() => setOpen(o => !o)}
        className={`w-full bg-spotify-gray rounded-lg text-sm text-left flex items-center justify-between
          outline-none focus:ring-2 focus:ring-spotify-green/50 ${
          compact ? 'px-2.5 py-1.5 text-xs' : 'px-4 py-2.5'
        } ${current ? 'text-white' : 'text-spotify-text'}`}
      >
        {current?.label || placeholder || 'Выберите'}
        <svg className={`w-4 h-4 text-zinc-400 transition-transform shrink-0 ml-1.5 ${open ? 'rotate-180' : ''}`}
          viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.15 }}
            className="absolute z-50 top-full left-0 right-0 mt-1 bg-spotify-gray rounded-lg overflow-hidden shadow-xl max-h-64 overflow-y-auto"
          >
            {options.map(f => (
              <button
                key={f.value}
                onClick={() => { onChange(f.value); setOpen(false) }}
                className={`w-full text-left px-4 py-2.5 text-sm transition-colors ${
                  String(f.value) === String(value)
                    ? 'text-spotify-green bg-white/5'
                    : 'text-white hover:bg-white/5'
                }`}
              >
                {f.label}
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
