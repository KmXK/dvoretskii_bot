import { createContext, useCallback, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'

export const ToastContext = createContext(null)

const STYLES = {
  success: 'bg-green-500/95 border-green-400 text-white',
  error: 'bg-red-500/95 border-red-400 text-white',
  info: 'bg-blue-500/95 border-blue-400 text-white',
}

const ICONS = { success: '✓', error: '⚠', info: 'ℹ' }

const DEFAULT_TTL = 4000

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const idRef = useRef(0)

  const dismiss = useCallback((id) => {
    setToasts(prev => prev.filter(t => t.id !== id))
  }, [])

  const show = useCallback((type, message, opts = {}) => {
    const id = ++idRef.current
    const ttl = opts.ttl ?? DEFAULT_TTL
    setToasts(prev => [...prev, { id, type, message }])
    if (ttl > 0) setTimeout(() => dismiss(id), ttl)
    return id
  }, [dismiss])

  const api = useMemo(() => ({
    success: (msg, opts) => show('success', msg, opts),
    error: (msg, opts) => show('error', msg, opts),
    info: (msg, opts) => show('info', msg, opts),
    dismiss,
  }), [show, dismiss])

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="fixed top-4 right-4 z-[200] flex flex-col gap-2 pointer-events-none max-w-[calc(100%-2rem)]">
        <AnimatePresence>
          {toasts.map(t => (
            <motion.div
              key={t.id}
              layout
              initial={{ opacity: 0, x: 80, scale: 0.9 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: 80, scale: 0.9 }}
              transition={{ type: 'spring', stiffness: 380, damping: 30 }}
              role="status"
              onClick={() => dismiss(t.id)}
              className={`pointer-events-auto cursor-pointer rounded-lg border px-4 py-2.5 shadow-lg flex items-start gap-2 text-sm font-medium backdrop-blur-sm ${STYLES[t.type] ?? STYLES.info}`}
            >
              <span className="shrink-0 font-bold">{ICONS[t.type] ?? ICONS.info}</span>
              <span className="flex-1 break-words">{t.message}</span>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  )
}
