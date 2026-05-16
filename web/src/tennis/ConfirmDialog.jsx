import { useCallback, useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'

function ConfirmDialog({ title, description, confirmLabel, cancelLabel, destructive, onConfirm, onCancel }) {
  // ESC = отмена
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onCancel() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onCancel])

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-[60] bg-black/60 backdrop-blur-sm flex items-center justify-center px-4"
      onClick={onCancel}
    >
      <motion.div
        initial={{ y: 30, scale: 0.95, opacity: 0 }}
        animate={{ y: 0, scale: 1, opacity: 1 }}
        exit={{ scale: 0.95, opacity: 0 }}
        transition={{ type: 'spring', damping: 24, stiffness: 320 }}
        className="bg-zinc-900 border border-zinc-700 rounded-2xl shadow-2xl w-full max-w-sm p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-white font-semibold text-lg mb-1">{title}</h2>
        {description && (
          <p className="text-zinc-400 text-sm mb-4">{description}</p>
        )}
        <div className="flex gap-2 mt-2">
          <button
            onClick={onCancel}
            className="flex-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 py-2.5 rounded-xl font-medium"
          >
            {cancelLabel || 'Отмена'}
          </button>
          <button
            onClick={onConfirm}
            autoFocus
            className={`flex-1 py-2.5 rounded-xl font-medium text-white ${
              destructive
                ? 'bg-red-700 hover:bg-red-600'
                : 'bg-rose-700 hover:bg-rose-600'
            }`}
          >
            {confirmLabel || 'OK'}
          </button>
        </div>
      </motion.div>
    </motion.div>
  )
}

/**
 * Хук — даёт async confirm() как у window.confirm, но в стилистике сайта.
 *
 *   const { confirm, element } = useConfirmDialog()
 *   if (!await confirm({ title: 'Закрыть?', destructive: true })) return
 *   return <>{element}{...}</>
 */
export function useConfirmDialog() {
  const [opts, setOpts] = useState(null)

  const confirm = useCallback((options) => new Promise((resolve) => {
    setOpts({ ...options, resolve })
  }), [])

  const onConfirm = useCallback(() => {
    opts?.resolve?.(true)
    setOpts(null)
  }, [opts])

  const onCancel = useCallback(() => {
    opts?.resolve?.(false)
    setOpts(null)
  }, [opts])

  const element = (
    <AnimatePresence>
      {opts && (
        <ConfirmDialog
          title={opts.title}
          description={opts.description}
          confirmLabel={opts.confirmLabel}
          cancelLabel={opts.cancelLabel}
          destructive={opts.destructive}
          onConfirm={onConfirm}
          onCancel={onCancel}
        />
      )}
    </AnimatePresence>
  )

  return { confirm, element }
}
