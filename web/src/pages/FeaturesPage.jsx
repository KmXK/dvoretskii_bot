import { useState, useMemo, useEffect, useRef, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import * as Dialog from '@radix-ui/react-dialog'
import BackButton from '../components/BackButton'
import Dropdown from '../components/Dropdown'
import { useTelegram } from '../context/TelegramContext'

const STATUS = { OPEN: 0, DONE: 1, DENIED: 2, IN_PROGRESS: 3, TESTING: 4 }

const STATUS_CONFIG = {
  [STATUS.OPEN]: { label: 'Открыт', class: 'bg-blue-500/20 text-blue-400', order: 2 },
  [STATUS.IN_PROGRESS]: { label: 'В работе', class: 'bg-yellow-500/20 text-yellow-400', order: 0 },
  [STATUS.TESTING]: { label: 'Тестирование', class: 'bg-purple-500/20 text-purple-400', order: 1 },
  [STATUS.DONE]: { label: 'Завершён', class: 'bg-green-500/20 text-green-400', order: 3 },
  [STATUS.DENIED]: { label: 'Отклонён', class: 'bg-red-500/20 text-red-400', order: 4 },
}

const STATUS_FILTERS = [
  { value: STATUS.OPEN, label: 'Открытые', class: 'bg-blue-500/20 text-blue-400 ring-blue-400/30' },
  { value: STATUS.IN_PROGRESS, label: 'В работе', class: 'bg-yellow-500/20 text-yellow-400 ring-yellow-400/30' },
  { value: STATUS.TESTING, label: 'Тестирование', class: 'bg-purple-500/20 text-purple-400 ring-purple-400/30' },
  { value: STATUS.DONE, label: 'Завершённые', class: 'bg-green-500/20 text-green-400 ring-green-400/30' },
  { value: STATUS.DENIED, label: 'Отклонённые', class: 'bg-red-500/20 text-red-400 ring-red-400/30' },
]

const SORT_OPTIONS = [
  { value: 'priority', label: 'По приоритету' },
  { value: 'id_asc', label: 'По ID ↑' },
  { value: 'id_desc', label: 'По ID ↓' },
  { value: 'status', label: 'По статусу' },
  { value: 'author', label: 'По автору' },
  { value: 'priority_status', label: 'Приоритет + статус' },
  { value: 'status_priority', label: 'Статус + приоритет' },
]

const PRIORITY_EMOJI = { 1: '🔴', 2: '🟠', 3: '🟡', 4: '🔵', 5: '⚪' }

const PAGE_SIZE = 10

function formatDate(timestamp) {
  if (!timestamp) return ''
  return new Date(timestamp * 1000).toLocaleDateString('ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric',
  })
}

function formatDateTime(timestamp) {
  if (!timestamp) return ''
  return new Date(timestamp * 1000).toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

function StatusFilter({ selected, onChange }) {
  const allSelected = selected.size === 0

  const toggle = (value) => {
    const next = new Set(selected)
    if (next.has(value)) next.delete(value)
    else next.add(value)
    onChange(next)
  }

  return (
    <div className="flex flex-wrap gap-1.5 mb-3">
      <button
        onClick={() => onChange(new Set())}
        className={`px-3 py-1.5 rounded-full text-xs font-medium transition-all ${
          allSelected
            ? 'bg-spotify-green/20 text-spotify-green ring-2 ring-spotify-green/30'
            : 'bg-white/5 text-spotify-text hover:bg-white/10'
        }`}
      >
        Все
      </button>
      {STATUS_FILTERS.map(f => {
        const active = selected.has(f.value)
        return (
          <button
            key={f.value}
            onClick={() => toggle(f.value)}
            className={`px-3 py-1.5 rounded-full text-xs font-medium transition-all ${
              active ? f.class + ' ring-2' : 'bg-white/5 text-spotify-text hover:bg-white/10'
            }`}
          >
            {f.label}
          </button>
        )
      })}
    </div>
  )
}

function FeatureCardModal({ feature, open, onClose, onSave }) {
  const [status, setStatus] = useState(feature?.status ?? STATUS.OPEN)
  const [priority, setPriority] = useState(feature?.priority ?? 5)
  const [newNote, setNewNote] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (feature) {
      setStatus(feature.status)
      setPriority(feature.priority)
      setNewNote('')
    }
  }, [feature])

  const handleSave = async () => {
    setSaving(true)
    const body = {}
    if (status !== feature.status) body.status = status
    if (priority !== feature.priority) body.priority = priority
    if (newNote.trim()) body.note = newNote.trim()

    if (Object.keys(body).length === 0) {
      onClose()
      setSaving(false)
      return
    }

    try {
      const res = await fetch(`/api/feature-requests/${feature.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (res.ok) {
        const updated = await res.json()
        onSave(updated)
      }
    } finally {
      setSaving(false)
    }
  }

  if (!feature) return null

  const cfg = STATUS_CONFIG[feature.status] ?? STATUS_CONFIG[STATUS.OPEN]

  return (
    <Dialog.Root open={open} onOpenChange={v => { if (!v) onClose() }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 z-50" />
        <Dialog.Content className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
          bg-spotify-dark rounded-2xl w-[calc(100%-2rem)] max-w-md max-h-[85vh] overflow-y-auto z-50 p-5">
          <Dialog.Title className="text-white text-lg font-bold mb-1">
            Фича-реквест #{feature.id}
          </Dialog.Title>

          <p className="text-white text-sm leading-relaxed mb-4">{feature.text}</p>

          <div className="grid grid-cols-2 gap-3 text-sm mb-4">
            <div className="text-spotify-text">Автор</div>
            <div className="text-white">{feature.author_name}</div>
            <div className="text-spotify-text">Дата</div>
            <div className="text-white">{formatDate(feature.creation_timestamp)}</div>
          </div>

          <div className="space-y-3 mb-4">
            <div>
              <label className="text-spotify-text text-xs mb-1 block">Статус</label>
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(STATUS_CONFIG).map(([key, val]) => (
                  <button
                    key={key}
                    onClick={() => setStatus(Number(key))}
                    className={`px-3 py-1.5 rounded-full text-xs font-medium transition-all ${
                      status === Number(key)
                        ? val.class + ' ring-2 ring-white/20'
                        : 'bg-white/5 text-spotify-text hover:bg-white/10'
                    }`}
                  >
                    {val.label}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="text-spotify-text text-xs mb-1 block">Приоритет</label>
              <div className="flex gap-1.5">
                {[1, 2, 3, 4, 5].map(p => (
                  <button
                    key={p}
                    onClick={() => setPriority(p)}
                    className={`w-10 h-10 rounded-lg text-sm font-medium transition-all flex items-center justify-center ${
                      priority === p
                        ? 'bg-spotify-green text-black ring-2 ring-spotify-green/30'
                        : 'bg-white/5 text-spotify-text hover:bg-white/10'
                    }`}
                  >
                    {PRIORITY_EMOJI[p]}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {feature.notes && feature.notes.length > 0 && (
            <div className="mb-4">
              <label className="text-spotify-text text-xs mb-2 block">Примечания</label>
              <div className="space-y-1.5">
                {feature.notes.map((note, i) => (
                  <div key={i} className="bg-white/5 rounded-lg px-3 py-2 text-white text-sm">
                    {note}
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="mb-4">
            <label className="text-spotify-text text-xs mb-1 block">Новое примечание</label>
            <textarea
              value={newNote}
              onChange={e => setNewNote(e.target.value)}
              placeholder="Добавить примечание..."
              rows={2}
              className="w-full bg-spotify-gray rounded-lg px-3 py-2 text-white text-sm
                placeholder-spotify-text outline-none focus:ring-2 focus:ring-spotify-green/50 resize-none"
            />
          </div>

          {feature.history && feature.history.length > 0 && (
            <div className="mb-4">
              <label className="text-spotify-text text-xs mb-2 block">История</label>
              <div className="space-y-1">
                {feature.history.map((h, i) => {
                  const hCfg = STATUS_CONFIG[h.status] ?? STATUS_CONFIG[STATUS.OPEN]
                  return (
                    <div key={i} className="flex items-center justify-between text-xs">
                      <span className={`px-2 py-0.5 rounded-full ${hCfg.class}`}>{hCfg.label}</span>
                      <span className="text-spotify-text">{formatDateTime(h.timestamp)}</span>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          <button
            onClick={handleSave}
            disabled={saving}
            className="w-full bg-spotify-green text-black font-semibold rounded-full py-2.5 text-sm
              hover:bg-green-400 transition-colors disabled:opacity-50"
          >
            {saving ? 'Сохранение...' : 'Сохранить'}
          </button>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

function CreateFeatureModal({ open, onClose, onCreate, authorName }) {
  const [text, setText] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (open) setText('')
  }, [open])

  const handleCreate = async () => {
    if (!text.trim()) return
    setSaving(true)
    try {
      const payload = { text: text.trim() }
      if (authorName) payload.author_name = authorName
      const res = await fetch('/api/feature-requests', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (res.ok) {
        const created = await res.json()
        onCreate(created)
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={v => { if (!v) onClose() }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 z-50" />
        <Dialog.Content className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
          bg-spotify-dark rounded-2xl w-[calc(100%-2rem)] max-w-md z-50 p-5">
          <Dialog.Title className="text-white text-lg font-bold mb-4">
            Новый фича-реквест
          </Dialog.Title>

          <textarea
            value={text}
            onChange={e => setText(e.target.value)}
            placeholder="Опишите фичу..."
            rows={4}
            autoFocus
            className="w-full bg-spotify-gray rounded-lg px-3 py-2.5 text-white text-sm
              placeholder-spotify-text outline-none focus:ring-2 focus:ring-spotify-green/50 resize-none mb-4"
          />

          <button
            onClick={handleCreate}
            disabled={saving || !text.trim()}
            className="w-full bg-spotify-green text-black font-semibold rounded-full py-2.5 text-sm
              hover:bg-green-400 transition-colors disabled:opacity-50"
          >
            {saving ? 'Создание...' : 'Создать'}
          </button>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

export default function FeaturesPage() {
  const { firstName, lastName, username } = useTelegram()
  const authorName = username || [firstName, lastName].filter(Boolean).join(' ') || ''

  const [features, setFeatures] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState(new Set([STATUS.OPEN, STATUS.IN_PROGRESS, STATUS.TESTING]))
  const [sort, setSort] = useState('priority')
  const [page, setPage] = useState(0)
  const [selectedFeature, setSelectedFeature] = useState(null)
  const [showCreate, setShowCreate] = useState(false)

  useEffect(() => {
    fetch('/api/feature-requests')
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then(data => { setFeatures(data); setLoading(false) })
      .catch(err => { setError(err.message); setLoading(false) })
  }, [])

  const handleSave = useCallback((updated) => {
    setFeatures(prev => prev.map(f => f.id === updated.id ? updated : f))
    setSelectedFeature(null)
  }, [])

  const handleCreate = useCallback((created) => {
    setFeatures(prev => [...prev, created])
    setShowCreate(false)
  }, [])

  const sortFn = useCallback((items) => {
    const copy = [...items]
    switch (sort) {
      case 'priority':
        return copy.sort((a, b) => a.priority - b.priority)
      case 'id_asc':
        return copy.sort((a, b) => a.id - b.id)
      case 'id_desc':
        return copy.sort((a, b) => b.id - a.id)
      case 'status':
        return copy.sort((a, b) =>
          (STATUS_CONFIG[a.status]?.order ?? 9) - (STATUS_CONFIG[b.status]?.order ?? 9)
        )
      case 'author':
        return copy.sort((a, b) => a.author_name.localeCompare(b.author_name))
      case 'priority_status':
        return copy.sort((a, b) =>
          a.priority - b.priority ||
          (STATUS_CONFIG[a.status]?.order ?? 9) - (STATUS_CONFIG[b.status]?.order ?? 9)
        )
      case 'status_priority':
        return copy.sort((a, b) =>
          (STATUS_CONFIG[a.status]?.order ?? 9) - (STATUS_CONFIG[b.status]?.order ?? 9) ||
          a.priority - b.priority
        )
      default:
        return copy
    }
  }, [sort])

  const filtered = useMemo(() => {
    let items = features
    if (statusFilter.size > 0) {
      items = items.filter(f => statusFilter.has(f.status))
    }

    if (search.trim()) {
      const q = search.toLowerCase()
      items = items.filter(
        f => f.text.toLowerCase().includes(q) || f.author_name.toLowerCase().includes(q) || String(f.id).includes(q)
      )
    }

    return sortFn(items)
  }, [features, statusFilter, search, sortFn])

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const currentPage = Math.min(page, totalPages - 1)
  const pageItems = filtered.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE)

  const goToPage = (p) => setPage(Math.max(0, Math.min(p, totalPages - 1)))

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-8 h-8 border-2 border-spotify-green border-t-transparent rounded-full animate-spin" />
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
      className="px-4 pt-6 pb-4"
    >
      <BackButton />
      <div className="flex items-center justify-between mb-1">
        <h1 className="text-2xl font-bold text-white">Фича-реквесты</h1>
        <button
          onClick={() => setShowCreate(true)}
          className="w-9 h-9 rounded-full bg-spotify-green text-black flex items-center justify-center
            text-xl font-bold hover:bg-green-400 transition-colors shrink-0"
        >
          +
        </button>
      </div>
      <p className="text-spotify-text text-sm mb-5">
        {filtered.length} {filtered.length === 1 ? 'запись' : filtered.length < 5 ? 'записи' : 'записей'}
      </p>

      <input
        type="text"
        placeholder="Поиск по тексту, автору или ID..."
        value={search}
        onChange={e => { setSearch(e.target.value); setPage(0) }}
        className="w-full bg-spotify-gray rounded-lg px-4 py-2.5 text-white text-sm
          placeholder-spotify-text outline-none focus:ring-2 focus:ring-spotify-green/50 mb-3"
      />

      <StatusFilter selected={statusFilter} onChange={v => { setStatusFilter(v); setPage(0) }} />
      <Dropdown value={sort} onChange={v => { setSort(v); setPage(0) }} options={SORT_OPTIONS} className="mb-4" />

      <div className="space-y-2">
        <AnimatePresence initial={false} mode="sync">
          {pageItems.map((fr) => {
            const cfg = STATUS_CONFIG[fr.status] ?? STATUS_CONFIG[STATUS.OPEN]
            return (
              <motion.div
                key={fr.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
                onClick={() => setSelectedFeature(fr)}
                className="bg-spotify-dark rounded-xl p-4 cursor-pointer active:scale-[0.98] transition-transform"
              >
                <div className="flex items-start justify-between gap-3 mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-spotify-text text-xs font-mono shrink-0">#{fr.id}</span>
                    <span className="text-sm" title={`Приоритет ${fr.priority}`}>
                      {PRIORITY_EMOJI[fr.priority] ?? '⚪'}
                    </span>
                  </div>
                  <span className={`px-2 py-0.5 rounded-full text-xs font-medium shrink-0 ${cfg.class}`}>
                    {cfg.label}
                  </span>
                </div>
                <p className="text-white text-sm leading-relaxed mb-2 line-clamp-2">{fr.text}</p>
                <div className="flex items-center justify-between text-xs text-spotify-text">
                  <span>{fr.author_name}</span>
                  <div className="flex items-center gap-2">
                    {fr.notes && fr.notes.length > 0 && (
                      <span className="text-spotify-text/60" title="Есть примечания">📝 {fr.notes.length}</span>
                    )}
                    <span>{formatDate(fr.creation_timestamp)}</span>
                  </div>
                </div>
              </motion.div>
            )
          })}
        </AnimatePresence>

        {pageItems.length === 0 && (
          <div className="text-center py-12 text-spotify-text text-sm">Ничего не найдено</div>
        )}
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 mt-5">
          <button
            onClick={() => goToPage(currentPage - 1)}
            disabled={currentPage === 0}
            className="w-8 h-8 rounded-lg bg-spotify-gray text-spotify-text text-sm
              disabled:opacity-30 hover:text-white transition-colors"
          >
            ‹
          </button>

          {Array.from({ length: totalPages }, (_, i) => (
            <button
              key={i}
              onClick={() => goToPage(i)}
              className={`w-8 h-8 rounded-lg text-sm font-medium transition-colors ${
                i === currentPage
                  ? 'bg-spotify-green text-black'
                  : 'bg-spotify-gray text-spotify-text hover:text-white'
              }`}
            >
              {i + 1}
            </button>
          ))}

          <button
            onClick={() => goToPage(currentPage + 1)}
            disabled={currentPage === totalPages - 1}
            className="w-8 h-8 rounded-lg bg-spotify-gray text-spotify-text text-sm
              disabled:opacity-30 hover:text-white transition-colors"
          >
            ›
          </button>
        </div>
      )}

      <FeatureCardModal
        feature={selectedFeature}
        open={!!selectedFeature}
        onClose={() => setSelectedFeature(null)}
        onSave={handleSave}
      />

      <CreateFeatureModal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreate={handleCreate}
        authorName={authorName}
      />
    </motion.div>
  )
}
