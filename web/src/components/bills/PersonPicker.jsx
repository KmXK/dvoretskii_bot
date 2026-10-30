import { useEffect, useId, useRef, useState } from 'react'
import { ChevronDown, Loader2, Plus, Search, Trash2, UserRound } from 'lucide-react'
import { api } from '../../api/client'

export default function PersonPicker({ people, selectedIds, onSelect, onCreated, onDeleted, disabled = false }) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const root = useRef(null)
  const input = useRef(null)
  const trigger = useRef(null)
  const listId = useId()
  const normalized = query.trim().replace(/^@/, '').toLowerCase()
  const matches = people.filter((person) => !person.deleted && !selectedIds.includes(person.id)
    && `${person.name || person.display_name} ${person.username || person.telegram_username || ''}`.toLowerCase().includes(normalized))
  const hasExactMatch = people.some((person) => !person.deleted && [
    person.name || person.display_name, person.username || person.telegram_username,
  ].some((value) => value && value.toLowerCase() === normalized))
  const activeId = matches[active] ? `${listId}-${matches[active].id}` : undefined

  useEffect(() => {
    if (open && activeId) document.getElementById(activeId)?.scrollIntoView({ block: 'nearest' })
  }, [activeId, open])

  useEffect(() => {
    if (!open) return
    input.current?.focus()
    const outside = (event) => {
      if (root.current && !root.current.contains(event.target)) setOpen(false)
    }
    document.addEventListener('pointerdown', outside)
    return () => document.removeEventListener('pointerdown', outside)
  }, [open])

  const choose = (person) => {
    onSelect(person)
    setQuery('')
    setActive(0)
    setOpen(false)
    setError(null)
    trigger.current?.focus()
  }

  const create = async () => {
    const raw = query.trim()
    if (!raw || busy) return
    setBusy(true)
    setError(null)
    try {
      const entry = raw.startsWith('@') ? { username: raw } : { name: raw }
      const data = await api.post('/api/bills/resolve-people', { participants: [entry] })
      const person = data.people?.[1]
      if (person) {
        const option = { ...person, name: person.display_name }
        onCreated(option)
        choose(option)
      }
    } catch (requestError) {
      setError(requestError.message || 'Не удалось добавить участника')
    } finally {
      setBusy(false)
    }
  }

  const remove = async (person) => {
    setBusy(true)
    setError(null)
    try {
      await api.delete(`/api/bills/persons/${person.id}`)
      onDeleted(person.id)
    } catch (requestError) {
      setError(requestError.message || 'Не удалось удалить участника')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div ref={root} className="relative mb-4" onKeyDown={(event) => {
      if (event.key === 'Escape') { setOpen(false); trigger.current?.focus(); event.stopPropagation() }
    }}>
      <button ref={trigger} type="button" disabled={disabled || busy} aria-expanded={open} aria-controls={listId}
        onClick={() => { setOpen((value) => !value); setError(null) }}
        className="w-full flex items-center gap-2 rounded-xl bg-spotify-gray px-4 py-3 text-left text-sm text-white disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-gold/50">
        <UserRound size={18} className="text-spotify-text" />
        <span className="flex-1">Добавить участника</span>
        <ChevronDown size={18} className={`text-spotify-text transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="absolute z-50 left-0 right-0 top-full mt-2 overflow-hidden rounded-xl border border-white/10 bg-spotify-gray shadow-2xl">
          <div className="flex items-center gap-2 border-b border-white/10 px-3 py-2">
            <Search size={16} className="shrink-0 text-spotify-text" />
            <input ref={input} value={query} role="combobox" aria-label="Поиск участников" aria-expanded={open}
              aria-controls={listId} aria-autocomplete="list" aria-activedescendant={activeId}
              placeholder="Имя или @username" disabled={busy}
              onChange={(event) => { setQuery(event.target.value); setActive(0); setError(null) }}
              onKeyDown={(event) => {
                if (event.key === 'ArrowDown') { event.preventDefault(); setActive((value) => Math.max(0, Math.min(value + 1, matches.length - 1))) }
                if (event.key === 'ArrowUp') { event.preventDefault(); setActive((value) => Math.max(value - 1, 0)) }
                if (event.key === 'Enter' && matches[active]) { event.preventDefault(); choose(matches[active]) }
              }}
              className="min-w-0 flex-1 bg-transparent py-2 text-sm text-white outline-none placeholder:text-spotify-text" />
            {busy && <Loader2 size={16} className="animate-spin text-gold" />}
          </div>
          <div id={listId} role="listbox" aria-label="Участники" className="max-h-64 overflow-y-auto overscroll-contain">
            {matches.map((person, index) => (
              <div key={person.id} className={`flex items-center ${index === active ? 'bg-white/5' : ''}`}>
                <button id={`${listId}-${person.id}`} type="button" role="option" aria-selected={false} disabled={busy}
                  onClick={() => choose(person)} onMouseEnter={() => setActive(index)}
                  className="min-w-0 flex-1 px-4 py-2.5 text-left hover:bg-white/5 focus:bg-white/10 focus:outline-none">
                  <span className="block truncate text-sm text-white">{person.name || person.display_name}</span>
                  <span className="block truncate text-xs text-spotify-text">
                    {person.username || person.telegram_username ? `@${person.username || person.telegram_username}` : person.telegram_id ? 'Без username в Telegram' : 'Временный участник'}
                  </span>
                </button>
                {person.created_by_me && !person.telegram_id && (
                  <button type="button" disabled={busy || !person.can_delete}
                    onClick={() => remove(person)} aria-label={`Удалить ${person.name || person.display_name}`}
                    title={person.delete_block_reason || 'Удалить временного участника'}
                    className="mr-2 rounded-lg p-2 text-spotify-text hover:bg-red-400/10 hover:text-red-400 disabled:opacity-25 disabled:hover:bg-transparent disabled:hover:text-spotify-text">
                    <Trash2 size={16} />
                  </button>
                )}
              </div>
            ))}
            {matches.length === 0 && <p className="px-4 py-4 text-sm text-spotify-text">Участники не найдены</p>}
          </div>
          {query.trim() && !hasExactMatch && (
            <button type="button" disabled={busy} onClick={create}
              className="flex w-full items-center gap-2 border-t border-white/10 px-4 py-3 text-left text-sm text-gold hover:bg-white/5 disabled:opacity-50">
              <Plus size={16} className="shrink-0" /><span className="break-words">Создать временного участника «{query.trim()}»</span>
            </button>
          )}
          {error && <p role="alert" className="border-t border-white/10 px-4 py-3 text-sm text-red-400">{error}</p>}
        </div>
      )}
    </div>
  )
}
