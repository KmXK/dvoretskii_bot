import { useState, useEffect, useMemo, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ListChecks } from 'lucide-react'
import BackButton from '../components/BackButton'
import Loader from '../components/Loader'
import { api } from '../api/client'

function TodoItem({ todo, onToggle }) {
  const [toggling, setToggling] = useState(false)

  const handleToggle = async () => {
    setToggling(true)
    try {
      const updated = await api.patch(`/api/todos/${todo.id}`)
      onToggle(updated)
    } catch { /* noop */ } finally {
      setToggling(false)
    }
  }

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95 }}
      transition={{ duration: 0.2 }}
      className="bg-spotify-dark rounded-xl p-4 flex items-start gap-3"
    >
      <button
        onClick={handleToggle}
        disabled={toggling}
        className={`w-5 h-5 rounded-md border-2 shrink-0 mt-0.5 transition-all flex items-center justify-center
          ${todo.is_done
            ? 'bg-spotify-green border-spotify-green'
            : 'border-white/20 hover:border-white/40'
          } ${toggling ? 'opacity-50' : ''}`}
      >
        {todo.is_done && (
          <svg className="w-3 h-3 text-black" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
            <path d="M5 13l4 4L19 7" />
          </svg>
        )}
      </button>
      <div className="flex-1 min-w-0">
        <p className={`text-sm leading-relaxed transition-all ${
          todo.is_done ? 'text-spotify-text line-through' : 'text-white'
        }`}>
          {todo.text}
        </p>
        <span className="text-xs text-spotify-text/50 mt-1 block">#{todo.id}</span>
      </div>
    </motion.div>
  )
}

export default function TodoPage() {
  const [todos, setTodos] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [showDone, setShowDone] = useState(false)

  useEffect(() => {
    api.get('/api/todos')
      .then(data => { setTodos(data); setLoading(false) })
      .catch(err => { setError(err.message); setLoading(false) })
  }, [])

  const handleToggle = useCallback((updated) => {
    setTodos(prev => prev.map(t => t.id === updated.id ? updated : t))
  }, [])

  const active = useMemo(() => todos.filter(t => !t.is_done), [todos])
  const done = useMemo(() => todos.filter(t => t.is_done), [todos])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader scale={0.7} />
      </div>
    )
  }

  if (error) {
    return (
      <div className="px-4 pt-6">
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 text-red-400 text-sm">
          Не удалось загрузить данные: {error}
        </div>
      </div>
    )
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="px-4 pt-6 pb-4 max-w-3xl mx-auto"
    >
      <BackButton />
      <h1 className="text-2xl font-bold text-white mb-1">Задачи</h1>
      <p className="text-spotify-text text-sm mb-5">
        {active.length} активных, {done.length} завершённых
      </p>

      {todos.length === 0 && (
        <div className="text-center py-16">
          <ListChecks size={48} className="mx-auto mb-4 text-spotify-text/60" />
          <p className="text-spotify-text text-sm">Задач пока нет</p>
        </div>
      )}

      {active.length > 0 && (
        <div className="space-y-2 mb-5">
          <AnimatePresence initial={false}>
            {active.map(todo => (
              <TodoItem key={todo.id} todo={todo} onToggle={handleToggle} />
            ))}
          </AnimatePresence>
        </div>
      )}

      {done.length > 0 && (
        <>
          <button
            onClick={() => setShowDone(v => !v)}
            className="flex items-center gap-2 text-spotify-text text-sm mb-3 hover:text-white transition-colors"
          >
            <svg
              className={`w-4 h-4 transition-transform ${showDone ? 'rotate-90' : ''}`}
              viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
            >
              <path d="M9 18l6-6-6-6" />
            </svg>
            Завершённые ({done.length})
          </button>

          <AnimatePresence initial={false}>
            {showDone && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                transition={{ duration: 0.2 }}
                className="space-y-2 overflow-hidden"
              >
                {done.map(todo => (
                  <TodoItem key={todo.id} todo={todo} onToggle={handleToggle} />
                ))}
              </motion.div>
            )}
          </AnimatePresence>
        </>
      )}
    </motion.div>
  )
}
