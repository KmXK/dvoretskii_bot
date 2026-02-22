import { useState, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import * as Dialog from '@radix-ui/react-dialog'
import BackButton from '../components/BackButton'
import { useTelegram } from '../context/TelegramContext'

const DAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

function formatInterval(sec) {
  if (!sec) return ''
  if (sec >= 86400 && sec % 86400 === 0) return `${sec / 86400}d`
  if (sec >= 3600 && sec % 3600 === 0) return `${sec / 3600}h`
  if (sec >= 60 && sec % 60 === 0) return `${sec / 60}m`
  return `${sec}s`
}

function ReminderCard({ reminder, onDelete, onEdit }) {
  const [deleting, setDeleting] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editText, setEditText] = useState(reminder.text)

  const handleDelete = async () => {
    setDeleting(true)
    await onDelete(reminder.id)
    setDeleting(false)
  }

  const handleEdit = async () => {
    if (!editText.trim() || editText === reminder.text) {
      setEditing(false)
      return
    }
    await onEdit(reminder.id, editText.trim())
    setEditing(false)
  }

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95 }}
      transition={{ duration: 0.2 }}
      className="bg-spotify-dark rounded-xl p-4"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          {editing ? (
            <div className="flex gap-2">
              <input
                type="text"
                value={editText}
                onChange={e => setEditText(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleEdit()}
                autoFocus
                className="flex-1 bg-spotify-gray rounded-lg px-3 py-1.5 text-white text-sm outline-none
                  focus:ring-1 focus:ring-spotify-green/50"
              />
              <button onClick={handleEdit} className="text-spotify-green text-sm shrink-0">✓</button>
              <button onClick={() => { setEditing(false); setEditText(reminder.text) }} className="text-spotify-text text-sm shrink-0">✕</button>
            </div>
          ) : (
            <p className="text-white text-sm">{reminder.text}</p>
          )}
          <div className="flex items-center gap-2 mt-2 flex-wrap">
            <span className="text-xs text-spotify-text">🔔 {reminder.next_fire_fmt}</span>
            {reminder.interval_seconds && (
              <span className="text-xs bg-blue-500/15 text-blue-400 px-1.5 py-0.5 rounded">
                каждые {formatInterval(reminder.interval_seconds)}
                {reminder.repeat_remaining != null && ` (x${reminder.repeat_remaining})`}
                {reminder.repeat_remaining == null && reminder.interval_seconds && ' (∞)'}
              </span>
            )}
            {reminder.days && (
              <span className="text-xs bg-purple-500/15 text-purple-400 px-1.5 py-0.5 rounded">
                {reminder.days.map(d => DAYS[d]).join(', ')}
              </span>
            )}
            <span className="text-xs text-spotify-text/50">{reminder.chat_name}</span>
          </div>
        </div>
        <div className="flex gap-1 shrink-0">
          {!editing && (
            <button
              onClick={() => setEditing(true)}
              className="p-1.5 text-spotify-text hover:text-white transition-colors text-xs"
              title="Редактировать"
            >
              ✏️
            </button>
          )}
          <button
            onClick={handleDelete}
            disabled={deleting}
            className="p-1.5 text-spotify-text hover:text-red-400 transition-colors text-xs disabled:opacity-50"
            title="Удалить"
          >
            🗑
          </button>
        </div>
      </div>
      <p className="text-[10px] text-spotify-text/40 mt-1">{reminder.id}</p>
    </motion.div>
  )
}

function CompletedCard({ reminder }) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="bg-spotify-dark rounded-xl p-4 opacity-60"
    >
      <p className="text-white text-sm line-through">{reminder.text}</p>
      <div className="flex items-center gap-2 mt-2">
        <span className="text-xs text-spotify-text">✅ {reminder.completed_at_fmt}</span>
        {reminder.fired_count > 1 && (
          <span className="text-xs text-spotify-text">(x{reminder.fired_count})</span>
        )}
        <span className="text-xs text-spotify-text/50">{reminder.chat_name}</span>
      </div>
    </motion.div>
  )
}

function CreateReminderDialog({ open, onOpenChange, chats, userId, onCreated }) {
  const [text, setText] = useState('')
  const [time, setTime] = useState('')
  const [chatId, setChatId] = useState('')
  const [repeat, setRepeat] = useState('')
  const [days, setDays] = useState([])
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (chats.length > 0 && !chatId) setChatId(String(chats[0].id))
  }, [chats, chatId])

  const toggleDay = (idx) => {
    setDays(prev => prev.includes(idx) ? prev.filter(d => d !== idx) : [...prev, idx].sort())
  }

  const handleCreate = async () => {
    if (!text.trim() || !time.trim() || !chatId) return
    setLoading(true)
    setError(null)
    try {
      const body = {
        user_id: userId,
        chat_id: parseInt(chatId),
        text: text.trim(),
        time: time.trim(),
      }
      if (repeat) body.repeat = repeat === '∞' ? '*' : repeat
      if (days.length > 0) body.days = days

      const res = await fetch('/api/reminders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error)
      onCreated(data)
      setText('')
      setTime('')
      setRepeat('')
      setDays([])
      onOpenChange(false)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 z-50" />
        <Dialog.Content className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-50
          bg-spotify-black rounded-2xl p-5 w-[calc(100%-2rem)] max-w-md max-h-[85vh] overflow-y-auto">
          <Dialog.Title className="text-white text-lg font-bold mb-4">Новое напоминание</Dialog.Title>

          <div className="space-y-3">
            <div>
              <label className="text-spotify-text text-xs mb-1 block">Чат</label>
              <select
                value={chatId}
                onChange={e => setChatId(e.target.value)}
                className="w-full bg-spotify-gray rounded-lg px-3 py-2.5 text-white text-sm outline-none"
              >
                {chats.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>

            <div>
              <label className="text-spotify-text text-xs mb-1 block">Время</label>
              <input
                type="text"
                value={time}
                onChange={e => setTime(e.target.value)}
                placeholder="10m, 2h30m, 15:30, 25.12 10:00"
                className="w-full bg-spotify-gray rounded-lg px-3 py-2.5 text-white text-sm outline-none
                  focus:ring-1 focus:ring-spotify-green/50"
              />
              <p className="text-spotify-text/50 text-[10px] mt-1">
                Интервал (10m, 2h), время (15:30), или дата (25.12 10:00)
              </p>
            </div>

            <div>
              <label className="text-spotify-text text-xs mb-1 block">Текст</label>
              <input
                type="text"
                value={text}
                onChange={e => setText(e.target.value)}
                placeholder="О чём напомнить?"
                className="w-full bg-spotify-gray rounded-lg px-3 py-2.5 text-white text-sm outline-none
                  focus:ring-1 focus:ring-spotify-green/50"
              />
            </div>

            <button
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="text-spotify-text text-xs hover:text-white transition-colors"
            >
              {showAdvanced ? '▾' : '▸'} Повторение и дни
            </button>

            {showAdvanced && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                className="space-y-3 overflow-hidden"
              >
                <div>
                  <label className="text-spotify-text text-xs mb-1 block">Повторений</label>
                  <div className="flex gap-1.5">
                    {['', '2', '3', '5', '10', '∞'].map(v => (
                      <button
                        key={v}
                        onClick={() => setRepeat(v)}
                        className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                          repeat === v
                            ? 'bg-spotify-green/20 text-spotify-green'
                            : 'bg-spotify-gray text-spotify-text hover:text-white'
                        }`}
                      >
                        {v || 'Нет'}
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <label className="text-spotify-text text-xs mb-1 block">Дни недели</label>
                  <div className="flex gap-1.5">
                    {DAYS.map((d, i) => (
                      <button
                        key={i}
                        onClick={() => toggleDay(i)}
                        className={`px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors flex-1 ${
                          days.includes(i)
                            ? 'bg-purple-500/20 text-purple-400'
                            : 'bg-spotify-gray text-spotify-text hover:text-white'
                        }`}
                      >
                        {d}
                      </button>
                    ))}
                  </div>
                </div>
              </motion.div>
            )}

            {error && (
              <p className="text-red-400 text-xs">{error}</p>
            )}

            <button
              onClick={handleCreate}
              disabled={loading || !text.trim() || !time.trim() || !chatId}
              className="w-full bg-spotify-green text-black font-semibold py-3 rounded-full
                hover:bg-spotify-green/90 disabled:opacity-50 disabled:cursor-not-allowed transition-all text-sm"
            >
              {loading ? 'Создаю...' : 'Создать'}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

export default function RemindersPage() {
  const { userId } = useTelegram()
  const [data, setData] = useState({ active: [], completed: [] })
  const [chats, setChats] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [showCompleted, setShowCompleted] = useState(false)
  const [showCreate, setShowCreate] = useState(false)

  useEffect(() => {
    if (!userId) return
    Promise.all([
      fetch(`/api/reminders/${userId}`).then(r => r.ok ? r.json() : { active: [], completed: [] }),
      fetch(`/api/user/${userId}/chats`).then(r => r.ok ? r.json() : { chats: [] }),
    ])
      .then(([remData, chatData]) => {
        setData(remData)
        setChats(chatData.chats || [])
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [userId])

  const handleDelete = useCallback(async (id) => {
    const res = await fetch(`/api/reminders/${id}?user_id=${userId}`, { method: 'DELETE' })
    if (res.ok) {
      setData(prev => ({
        ...prev,
        active: prev.active.filter(r => r.id !== id),
      }))
    }
  }, [userId])

  const handleEdit = useCallback(async (id, newText) => {
    const res = await fetch(`/api/reminders/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, text: newText }),
    })
    if (res.ok) {
      const updated = await res.json()
      setData(prev => ({
        ...prev,
        active: prev.active.map(r => r.id === id ? updated : r),
      }))
    }
  }, [userId])

  const handleCreated = useCallback((newReminder) => {
    setData(prev => ({
      ...prev,
      active: [...prev.active, newReminder].sort(
        (a, b) => new Date(a.next_fire) - new Date(b.next_fire)
      ),
    }))
  }, [])

  if (!userId) {
    return (
      <div className="flex items-center justify-center min-h-[60vh] px-4">
        <div className="bg-spotify-dark rounded-2xl p-6 text-center max-w-sm">
          <span className="text-4xl block mb-3">🔒</span>
          <h2 className="text-white font-semibold text-lg mb-2">Нет данных</h2>
          <p className="text-spotify-text text-sm">Откройте приложение через Telegram</p>
        </div>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-8 h-8 border-2 border-spotify-green border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="px-4 pt-6 pb-4"
    >
      <BackButton />

      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-bold text-white mb-0.5">Напоминания</h1>
          <p className="text-spotify-text text-sm">
            {data.active.length} активных
          </p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="bg-spotify-green text-black font-semibold px-4 py-2 rounded-full text-sm
            hover:bg-spotify-green/90 transition-all"
        >
          + Создать
        </button>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-3 text-red-400 text-sm mb-4">
          {error}
        </div>
      )}

      {data.active.length === 0 && data.completed.length === 0 && (
        <div className="text-center py-16">
          <span className="text-5xl block mb-4">🔔</span>
          <p className="text-spotify-text text-sm">Напоминаний пока нет</p>
        </div>
      )}

      {data.active.length > 0 && (
        <div className="space-y-2 mb-5">
          <AnimatePresence initial={false}>
            {data.active.map(r => (
              <ReminderCard key={r.id} reminder={r} onDelete={handleDelete} onEdit={handleEdit} />
            ))}
          </AnimatePresence>
        </div>
      )}

      {data.completed.length > 0 && (
        <>
          <button
            onClick={() => setShowCompleted(v => !v)}
            className="flex items-center gap-2 text-spotify-text text-sm mb-3 hover:text-white transition-colors"
          >
            <svg
              className={`w-4 h-4 transition-transform ${showCompleted ? 'rotate-90' : ''}`}
              viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
            >
              <path d="M9 18l6-6-6-6" />
            </svg>
            Завершённые ({data.completed.length})
          </button>
          <AnimatePresence initial={false}>
            {showCompleted && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                transition={{ duration: 0.2 }}
                className="space-y-2 overflow-hidden"
              >
                {data.completed.map(r => <CompletedCard key={r.id} reminder={r} />)}
              </motion.div>
            )}
          </AnimatePresence>
        </>
      )}

      <CreateReminderDialog
        open={showCreate}
        onOpenChange={setShowCreate}
        chats={chats}
        userId={userId}
        onCreated={handleCreated}
      />
    </motion.div>
  )
}
