import { useState, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import * as Dialog from '@radix-ui/react-dialog'
import BackButton from '../components/BackButton'
import Dropdown from '../components/Dropdown'
import { useTelegram } from '../context/TelegramContext'

const MONTHS = [
  'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
]

function isUpcoming(day, month) {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  let bd = new Date(now.getFullYear(), month - 1, day)
  if (bd < today) bd = new Date(now.getFullYear() + 1, month - 1, day)
  const diff = Math.ceil((bd - today) / 86400000)
  return diff
}

function BirthdayCard({ birthday, onDelete }) {
  const [deleting, setDeleting] = useState(false)
  const daysUntil = isUpcoming(birthday.day, birthday.month)
  const isToday = daysUntil === 0
  const isSoon = daysUntil <= 7

  const handleDelete = async () => {
    setDeleting(true)
    await onDelete(birthday)
    setDeleting(false)
  }

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95 }}
      transition={{ duration: 0.2 }}
      className={`bg-spotify-dark rounded-xl p-4 flex items-center gap-3 ${isToday ? 'ring-1 ring-yellow-400/40' : ''}`}
    >
      <div className={`w-10 h-10 rounded-lg flex items-center justify-center text-lg shrink-0 ${
        isToday ? 'bg-yellow-500/20' : isSoon ? 'bg-green-500/15' : 'bg-spotify-gray'
      }`}>
        {isToday ? '🎂' : '🎁'}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-white text-sm font-medium truncate">{birthday.name}</p>
        <p className="text-spotify-text text-xs">
          {birthday.day} {birthday.month_name}
          {isToday && <span className="text-yellow-400 ml-2">Сегодня! 🎉</span>}
          {!isToday && isSoon && <span className="text-green-400 ml-2">через {daysUntil} дн.</span>}
          {!isToday && !isSoon && <span className="text-spotify-text/50 ml-2">через {daysUntil} дн.</span>}
        </p>
      </div>
      <button
        onClick={handleDelete}
        disabled={deleting}
        className="p-1.5 text-spotify-text hover:text-red-400 transition-colors text-xs disabled:opacity-50 shrink-0"
      >
        🗑
      </button>
    </motion.div>
  )
}

function CreateBirthdayDialog({ open, onOpenChange, chats, onCreated }) {
  const [name, setName] = useState('')
  const [day, setDay] = useState('')
  const [month, setMonth] = useState('')
  const [chatId, setChatId] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (chats.length > 0 && !chatId) setChatId(String(chats[0].id))
  }, [chats, chatId])

  const handleCreate = async () => {
    if (!name.trim() || !day || !month || !chatId) return
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/birthdays', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name.trim(),
          day: parseInt(day),
          month: parseInt(month),
          chat_id: parseInt(chatId),
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error)
      onCreated(data)
      setName('')
      setDay('')
      setMonth('')
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
          bg-spotify-black rounded-2xl p-5 w-[calc(100%-2rem)] max-w-md">
          <Dialog.Title className="text-white text-lg font-bold mb-4">Добавить день рождения</Dialog.Title>

          <div className="space-y-3">
            <div>
              <label className="text-spotify-text text-xs mb-1 block">Чат</label>
              <Dropdown
                value={chatId}
                onChange={v => setChatId(v)}
                options={chats.map(c => ({ value: c.id, label: c.name }))}
              />
            </div>

            <div>
              <label className="text-spotify-text text-xs mb-1 block">Имя</label>
              <input
                type="text"
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder="Имя именинника"
                className="w-full bg-spotify-gray rounded-lg px-3 py-2.5 text-white text-sm outline-none
                  focus:ring-1 focus:ring-spotify-green/50"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-spotify-text text-xs mb-1 block">День</label>
                <input
                  type="number"
                  value={day}
                  onChange={e => setDay(e.target.value)}
                  min="1" max="31"
                  placeholder="ДД"
                  className="w-full bg-spotify-gray rounded-lg px-3 py-2.5 text-white text-sm outline-none
                    focus:ring-1 focus:ring-spotify-green/50"
                />
              </div>
              <div>
                <label className="text-spotify-text text-xs mb-1 block">Месяц</label>
                <Dropdown
                  value={month}
                  onChange={v => setMonth(v)}
                  placeholder="Выберите"
                  options={MONTHS.map((m, i) => ({ value: i + 1, label: m }))}
                />
              </div>
            </div>

            {error && <p className="text-red-400 text-xs">{error}</p>}

            <button
              onClick={handleCreate}
              disabled={loading || !name.trim() || !day || !month || !chatId}
              className="w-full bg-spotify-green text-black font-semibold py-3 rounded-full
                hover:bg-spotify-green/90 disabled:opacity-50 disabled:cursor-not-allowed transition-all text-sm"
            >
              {loading ? 'Добавляю...' : 'Добавить'}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

export default function BirthdaysPage() {
  const { userId } = useTelegram()
  const [birthdays, setBirthdays] = useState([])
  const [chats, setChats] = useState([])
  const [selectedChat, setSelectedChat] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [showCreate, setShowCreate] = useState(false)

  useEffect(() => {
    if (!userId) return
    fetch(`/api/user/${userId}/chats`)
      .then(r => r.ok ? r.json() : { chats: [] })
      .then(data => {
        const ch = data.chats || []
        setChats(ch)
        if (ch.length > 0) setSelectedChat(String(ch[0].id))
      })
      .catch(e => setError(e.message))
  }, [userId])

  useEffect(() => {
    if (!selectedChat) { setLoading(false); return }
    setLoading(true)
    fetch(`/api/birthdays?chat_id=${selectedChat}`)
      .then(r => r.ok ? r.json() : [])
      .then(data => setBirthdays(data))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [selectedChat])

  const handleDelete = useCallback(async (birthday) => {
    const res = await fetch('/api/birthdays', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: birthday.name, chat_id: birthday.chat_id }),
    })
    if (res.ok) {
      setBirthdays(prev => prev.filter(b => !(b.name === birthday.name && b.chat_id === birthday.chat_id)))
    }
  }, [])

  const handleCreated = useCallback((newBirthday) => {
    if (String(newBirthday.chat_id) === selectedChat) {
      setBirthdays(prev => {
        const filtered = prev.filter(b => b.name !== newBirthday.name)
        return [...filtered, newBirthday].sort((a, b) => a.month - b.month || a.day - b.day)
      })
    }
  }, [selectedChat])

  const sortedBirthdays = [...birthdays].sort((a, b) => {
    const da = isUpcoming(a.day, a.month)
    const db = isUpcoming(b.day, b.month)
    return da - db
  })

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

  if (loading && birthdays.length === 0) {
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
          <h1 className="text-2xl font-bold text-white mb-0.5">Дни рождения</h1>
          <p className="text-spotify-text text-sm">{birthdays.length} записей</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="bg-spotify-green text-black font-semibold px-4 py-2 rounded-full text-sm
            hover:bg-spotify-green/90 transition-all"
        >
          + Добавить
        </button>
      </div>

      {chats.length > 1 && (
        <div className="flex gap-1 mb-4 bg-spotify-dark rounded-xl p-1 overflow-x-auto">
          {chats.map(c => (
            <button
              key={c.id}
              onClick={() => setSelectedChat(String(c.id))}
              className={`px-3 py-2 rounded-lg text-xs font-medium transition-all whitespace-nowrap shrink-0 ${
                selectedChat === String(c.id)
                  ? 'bg-spotify-green text-black'
                  : 'text-spotify-text hover:text-white'
              }`}
            >
              {c.name}
            </button>
          ))}
        </div>
      )}

      {error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-3 text-red-400 text-sm mb-4">
          {error}
        </div>
      )}

      {sortedBirthdays.length === 0 && !loading && (
        <div className="text-center py-16">
          <span className="text-5xl block mb-4">🎂</span>
          <p className="text-spotify-text text-sm">Именинников пока нет</p>
        </div>
      )}

      <div className="space-y-2">
        <AnimatePresence initial={false}>
          {sortedBirthdays.map(b => (
            <BirthdayCard
              key={`${b.chat_id}-${b.name}`}
              birthday={b}
              onDelete={handleDelete}
            />
          ))}
        </AnimatePresence>
      </div>

      <CreateBirthdayDialog
        open={showCreate}
        onOpenChange={setShowCreate}
        chats={chats}
        onCreated={handleCreated}
      />
    </motion.div>
  )
}
