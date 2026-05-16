import { useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { tennisApi } from './api'
import { useConfirmDialog } from './ConfirmDialog'

function isValidPartyScore(a, b) {
  if (a === b) return false
  const hi = Math.max(a, b), lo = Math.min(a, b)
  return hi >= 11 && hi - lo >= 2
}

// Универсальная модалка редактирования счёта партии — используется и при
// исправлении ошибочно записанной партии в активной сессии, и в истории.
export function EditMatchSheet({ open, nameA, nameB, initialScoreA, initialScoreB, onSave, onClose }) {
  const [a, setA] = useState(initialScoreA ?? 11)
  const [b, setB] = useState(initialScoreB ?? 7)
  useEffect(() => {
    if (open) {
      setA(initialScoreA ?? 11)
      setB(initialScoreB ?? 7)
    }
  }, [open, initialScoreA, initialScoreB])

  if (!open) return null
  const valid = isValidPartyScore(a, b)
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-[55] bg-black/70 backdrop-blur-sm flex items-end justify-center"
      onClick={onClose}
    >
      <motion.div
        initial={{ y: '100%' }}
        animate={{ y: 0 }}
        exit={{ y: '100%' }}
        transition={{ type: 'spring', damping: 26, stiffness: 280 }}
        className="bg-zinc-900 border-t border-zinc-700 w-full max-w-2xl rounded-t-2xl shadow-2xl"
        style={{ paddingBottom: 'calc(env(safe-area-inset-bottom) + 14px)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-800">
          <h2 className="text-white font-bold text-lg">Поправить счёт партии</h2>
          <button onClick={onClose} className="text-zinc-400 hover:text-white text-3xl leading-none px-2">×</button>
        </div>
        <div className="px-4 py-3">
          {/* Текущий счёт */}
          <div className="flex items-center justify-center mb-4 gap-3">
            <div className="flex-1 text-right">
              <div className="text-rose-300/80 text-xs uppercase tracking-wider mb-1 truncate">{nameA}</div>
              <div className="text-5xl font-black text-white tabular-nums">{a}</div>
            </div>
            <span className="text-3xl text-zinc-500 pb-2">:</span>
            <div className="flex-1">
              <div className="text-sky-300/80 text-xs uppercase tracking-wider mb-1 truncate">{nameB}</div>
              <div className="text-5xl font-black text-white tabular-nums">{b}</div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 mb-3">
            <div className="flex items-center gap-2">
              <button onClick={() => setA((n) => Math.max(0, n - 1))}
                className="w-12 h-12 rounded-xl bg-zinc-800 hover:bg-zinc-700 text-white text-2xl font-bold">−</button>
              <div className="flex-1 bg-zinc-800 rounded-xl py-2 text-center text-white text-xl font-bold">{a}</div>
              <button onClick={() => setA((n) => Math.min(50, n + 1))}
                className="w-12 h-12 rounded-xl bg-zinc-800 hover:bg-zinc-700 text-white text-2xl font-bold">+</button>
            </div>
            <div className="flex items-center gap-2">
              <button onClick={() => setB((n) => Math.max(0, n - 1))}
                className="w-12 h-12 rounded-xl bg-zinc-800 hover:bg-zinc-700 text-white text-2xl font-bold">−</button>
              <div className="flex-1 bg-zinc-800 rounded-xl py-2 text-center text-white text-xl font-bold">{b}</div>
              <button onClick={() => setB((n) => Math.min(50, n + 1))}
                className="w-12 h-12 rounded-xl bg-zinc-800 hover:bg-zinc-700 text-white text-2xl font-bold">+</button>
            </div>
          </div>

          <p className="text-zinc-500 text-[11px] mb-3 text-center">
            Правило: 11+ у победителя, разница ≥2.
          </p>

          <button
            onClick={() => valid && onSave(a, b)}
            disabled={!valid}
            className={`w-full rounded-2xl py-4 font-bold text-lg ${
              valid ? 'bg-gradient-to-br from-emerald-500 to-emerald-700 text-white shadow-lg' : 'bg-zinc-800 text-zinc-500'
            }`}
          >
            {valid ? `✓ Сохранить ${a}:${b}` : `${a}:${b} — нужен валидный счёт`}
          </button>
        </div>
      </motion.div>
    </motion.div>
  )
}

function SheetShell({ title, onClose, children, maxHeight = '90svh' }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      // z-50: поверх BottomNav (z-40), иначе нижняя кнопка модалки залезет под мобильную навигацию
      className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-end justify-center"
      onClick={onClose}
    >
      <motion.div
        initial={{ y: '100%' }}
        animate={{ y: 0 }}
        exit={{ y: '100%' }}
        transition={{ type: 'spring', damping: 26, stiffness: 280 }}
        className="bg-zinc-900 border-t border-zinc-700 w-full max-w-2xl rounded-t-2xl shadow-2xl overflow-y-auto"
        style={{
          maxHeight,
          // 14px (зазор) + safe-area-inset-bottom + 56px (высота BottomNav h-14)
          // чтобы submit-кнопки внутри sheet не закрывались мобильным навбаром
          paddingBottom: 'calc(env(safe-area-inset-bottom) + 70px)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 bg-zinc-900 z-10 flex items-center justify-between px-4 py-3 border-b border-zinc-800">
          <h2 className="text-white font-semibold">{title}</h2>
          <button onClick={onClose} className="text-zinc-400 hover:text-white text-2xl leading-none">×</button>
        </div>
        <div className="px-4 py-3">{children}</div>
      </motion.div>
    </motion.div>
  )
}

// ── NewSessionSheet ───────────────────────────────────────────────────────────

export function NewSessionSheet({ open, onClose, onCreated }) {
  const [opponents, setOpponents] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [customRaw, setCustomRaw] = useState('')
  const [firstServer, setFirstServer] = useState('a')
  const [serveStreak, setServeStreak] = useState(2)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!open) return
    setError(null)
    tennisApi.listOpponents()
      .then((d) => setOpponents(d.opponents || []))
      .catch((e) => setError(e.message || 'Не вышло загрузить кандидатов'))
  }, [open])

  const submit = async () => {
    setError(null)
    const opponent = selectedId != null ? selectedId : customRaw.trim()
    if (!opponent && opponent !== 0) {
      setError('Выбери оппонента или впиши @username')
      return
    }
    setSubmitting(true)
    try {
      const created = await tennisApi.createSession({
        opponent,
        first_server: firstServer,
        serve_streak: serveStreak,
      })
      onCreated(created)
    } catch (e) {
      let msg = e.message || 'Ошибка'
      // распарсим JSON-ошибку aiohttp
      try {
        const parsed = JSON.parse(msg)
        if (parsed?.error) msg = parsed.error
      } catch { /* not json */ }
      setError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  if (!open) return null
  return (
    <AnimatePresence>
      <SheetShell title="Новая сессия" onClose={onClose}>
        <div className="text-xs uppercase tracking-wider text-zinc-500 mb-2">Оппонент</div>
        {opponents.length === 0 ? (
          <p className="text-zinc-500 text-sm mb-3">Кандидатов из общих чатов не нашлось — впиши @username вручную.</p>
        ) : (
          <div className="flex flex-wrap gap-2 mb-3">
            {opponents.slice(0, 12).map((o) => (
              <button
                key={o.id}
                onClick={() => { setSelectedId(o.id); setCustomRaw('') }}
                className={`px-3 py-1.5 rounded-full text-sm border ${
                  selectedId === o.id
                    ? 'bg-rose-700 border-rose-500 text-white'
                    : 'bg-zinc-800 border-zinc-700 text-zinc-200 hover:border-zinc-500'
                }`}
              >
                {o.name}
                {o.played_against > 0 && (
                  <span className="ml-1 text-[10px] opacity-70">·{o.played_against}</span>
                )}
              </button>
            ))}
          </div>
        )}
        <input
          type="text"
          value={customRaw}
          onChange={(e) => { setCustomRaw(e.target.value); setSelectedId(null) }}
          placeholder="@username или id"
          className="w-full bg-zinc-800 text-white text-sm px-3 py-2 rounded-lg border border-zinc-700 mb-4"
        />

        <div className="text-xs uppercase tracking-wider text-zinc-500 mb-2">Кто подаёт первым</div>
        <div className="grid grid-cols-2 gap-2 mb-4">
          <button
            onClick={() => setFirstServer('a')}
            className={`py-2.5 rounded-lg text-sm font-medium ${
              firstServer === 'a' ? 'bg-rose-700 text-white' : 'bg-zinc-800 text-zinc-300'
            }`}
          >
            🏓 Я
          </button>
          <button
            onClick={() => setFirstServer('b')}
            className={`py-2.5 rounded-lg text-sm font-medium ${
              firstServer === 'b' ? 'bg-sky-700 text-white' : 'bg-zinc-800 text-zinc-300'
            }`}
          >
            🏓 Оппонент
          </button>
        </div>

        <div className="text-xs uppercase tracking-wider text-zinc-500 mb-2">Партий за одну подачу</div>
        <p className="text-zinc-500 text-[11px] mb-2">
          Каждые N партий первая подача переходит к другому игроку.
        </p>
        <div className="flex items-center gap-2 mb-4">
          {[1, 2, 5].map((n) => (
            <button
              key={n}
              onClick={() => setServeStreak(n)}
              className={`px-4 py-2 rounded-lg text-sm font-medium ${
                serveStreak === n ? 'bg-rose-700 text-white' : 'bg-zinc-800 text-zinc-300'
              }`}
            >
              {n}
            </button>
          ))}
          <input
            type="number"
            min={1}
            value={serveStreak}
            onChange={(e) => setServeStreak(Math.max(1, parseInt(e.target.value || '1', 10)))}
            className="w-16 bg-zinc-800 text-white text-sm px-2 py-1.5 rounded-lg border border-zinc-700 ml-auto"
          />
        </div>

        {error && (
          <p className="text-red-400 text-sm mb-3">{error}</p>
        )}

        <button
          onClick={submit}
          disabled={submitting}
          className="w-full bg-gradient-to-br from-rose-600 to-rose-800 text-white py-3 rounded-xl font-semibold text-lg disabled:opacity-50"
        >
          {submitting ? 'Создаём…' : 'Начать'}
        </button>
      </SheetShell>
    </AnimatePresence>
  )
}

// ── ImportSheet ───────────────────────────────────────────────────────────────

// Позиция каретки в пикселях внутри textarea. Стандартный приём: клонируем
// стили в скрытый div, кладём в него текст до каретки + маркер-span, читаем
// его offsetTop/offsetLeft.
const _MIRROR_PROPS = [
  'direction', 'boxSizing', 'width', 'height', 'overflowX', 'overflowY',
  'borderTopWidth', 'borderRightWidth', 'borderBottomWidth', 'borderLeftWidth', 'borderStyle',
  'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft',
  'fontStyle', 'fontVariant', 'fontWeight', 'fontStretch', 'fontSize', 'fontSizeAdjust',
  'lineHeight', 'fontFamily', 'textAlign', 'textTransform', 'textIndent',
  'textDecoration', 'letterSpacing', 'wordSpacing', 'tabSize',
]

function getCaretCoordinates(el, position) {
  const div = document.createElement('div')
  const computed = window.getComputedStyle(el)
  const s = div.style
  s.whiteSpace = 'pre-wrap'
  s.wordWrap = 'break-word'
  s.position = 'absolute'
  s.visibility = 'hidden'
  s.top = '0'
  s.left = '-9999px'
  for (const p of _MIRROR_PROPS) s[p] = computed[p]
  document.body.appendChild(div)
  div.textContent = el.value.slice(0, position)
  const marker = document.createElement('span')
  marker.textContent = el.value.slice(position) || '.'
  div.appendChild(marker)
  const top = marker.offsetTop + parseInt(computed.borderTopWidth || '0', 10)
  const left = marker.offsetLeft + parseInt(computed.borderLeftWidth || '0', 10)
  const lineHeight = parseInt(computed.lineHeight || '0', 10) || parseInt(computed.fontSize, 10) * 1.2
  document.body.removeChild(div)
  return { top, left, lineHeight }
}

const IMPORT_EXAMPLE = `2024-05-10 @ivan 5:3
2024-05-12 @ivan 7:2
2024-05-15 @ivan
11:7
11:9
9:11
12:10
2024-05-20 @ivan 4:6`

export function ImportSheet({ open, onClose, onImported }) {
  const [text, setText] = useState('')
  const [preview, setPreview] = useState(null)
  const [parsing, setParsing] = useState(false)
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [opponents, setOpponents] = useState([])
  const [suggest, setSuggest] = useState(null)   // {start, end, query, highlighted}
  const textareaRef = useRef(null)

  useEffect(() => {
    if (!open) {
      setText('')
      setPreview(null)
      setError(null)
      setSuggest(null)
      return
    }
    // тянем кандидатов для @-автокомплита
    tennisApi.listOpponents()
      .then((d) => setOpponents(d.opponents || []))
      .catch(() => setOpponents([]))
  }, [open])

  // Парсим состояние «пишет @-handle» — ищем последний @ перед кареткой
  const updateSuggest = (newText, caret) => {
    let i = caret - 1
    while (i >= 0 && /[\w_]/.test(newText[i])) i--
    if (i < 0 || newText[i] !== '@') {
      setSuggest(null)
      return
    }
    const start = i
    const end = caret
    if (start > 0 && !/\s/.test(newText[start - 1])) {
      setSuggest(null)
      return
    }
    const query = newText.slice(start + 1, end).toLowerCase()
    const ta = textareaRef.current
    let coords = null
    if (ta) {
      try {
        const c = getCaretCoordinates(ta, end)
        coords = {
          top: c.top + c.lineHeight - ta.scrollTop,
          left: c.left - ta.scrollLeft,
          lineHeight: c.lineHeight,
        }
      } catch { /* ignore */ }
    }
    setSuggest((prev) => ({
      start,
      end,
      query,
      coords,
      highlighted: prev && prev.start === start ? prev.highlighted : 0,
    }))
  }

  const filteredOpponents = useMemo(() => {
    if (!suggest) return []
    const q = suggest.query
    return opponents
      .filter((o) => o.username && o.username.toLowerCase().includes(q))
      .slice(0, 6)
  }, [opponents, suggest])

  const applySuggestion = (opp) => {
    if (!suggest || !opp?.username) return
    const before = text.slice(0, suggest.start)
    const after = text.slice(suggest.end)
    const insert = `@${opp.username}`
    const newText = before + insert + after
    const newCaret = before.length + insert.length
    setText(newText)
    setSuggest(null)
    // вернём фокус и каретку
    window.setTimeout(() => {
      const ta = textareaRef.current
      if (ta) {
        ta.focus()
        ta.setSelectionRange(newCaret, newCaret)
      }
    }, 0)
  }

  const handleTextareaKeyDown = (e) => {
    if (!suggest || filteredOpponents.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSuggest((s) => ({ ...s, highlighted: (s.highlighted + 1) % filteredOpponents.length }))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSuggest((s) => ({ ...s, highlighted: (s.highlighted - 1 + filteredOpponents.length) % filteredOpponents.length }))
    } else if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault()
      applySuggestion(filteredOpponents[suggest.highlighted])
    } else if (e.key === 'Escape') {
      e.preventDefault()
      setSuggest(null)
    }
  }

  const handleTextareaChange = (e) => {
    const v = e.target.value
    setText(v)
    updateSuggest(v, e.target.selectionStart ?? v.length)
  }

  const handleTextareaSelect = (e) => {
    updateSuggest(text, e.target.selectionStart ?? text.length)
  }

  // Live parsing (debounced)
  useEffect(() => {
    if (!open) return
    if (!text.trim()) { setPreview(null); setError(null); return }
    const id = window.setTimeout(async () => {
      setParsing(true)
      try {
        const d = await tennisApi.parseImport(text)
        setPreview(d.entries || [])
        setError(null)
      } catch (e) {
        let msg = e.message || 'Ошибка'
        try {
          const parsed = JSON.parse(msg)
          if (parsed?.error) msg = parsed.error
        } catch { /* */ }
        setError(msg)
        setPreview(null)
      } finally {
        setParsing(false)
      }
    }, 400)
    return () => window.clearTimeout(id)
  }, [text, open])

  const unresolved = useMemo(
    () => preview ? preview.filter((e) => !e.opponent_id) : [],
    [preview]
  )
  const canSubmit = preview && preview.length > 0 && unresolved.length === 0

  const submit = async () => {
    if (!canSubmit) return
    setSubmitting(true)
    setError(null)
    try {
      const d = await tennisApi.commitImport(text)
      onImported(d.created || [])
    } catch (e) {
      let msg = e.message || 'Ошибка'
      try {
        const parsed = JSON.parse(msg)
        if (parsed?.error) msg = parsed.error
      } catch { /* */ }
      setError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  if (!open) return null
  return (
    <AnimatePresence>
      <SheetShell title="Импорт истории" onClose={onClose}>
        <p className="text-zinc-400 text-xs mb-2">
          Формат: «ГГГГ-ММ-ДД @opp» (потом партии 11:7), либо «ГГГГ-ММ-ДД @opp 5:3» для агрегата.
          Пустые строки игнорятся.
        </p>
        <div className="relative">
          <textarea
            ref={textareaRef}
            value={text}
            onChange={handleTextareaChange}
            onKeyDown={handleTextareaKeyDown}
            onSelect={handleTextareaSelect}
            onClick={handleTextareaSelect}
            onScroll={(e) => { if (suggest) updateSuggest(text, e.target.selectionStart ?? text.length) }}
            onBlur={() => window.setTimeout(() => setSuggest(null), 150)}
            placeholder={IMPORT_EXAMPLE}
            rows={10}
            className="w-full bg-zinc-800 text-white text-sm px-3 py-2 rounded-lg border border-zinc-700 font-mono"
            style={{ minHeight: 220 }}
          />
          {suggest && filteredOpponents.length > 0 && (
            <div
              className="absolute z-20 bg-zinc-950 border border-zinc-700 rounded-lg shadow-xl overflow-hidden max-h-60 overflow-y-auto min-w-[220px]"
              style={
                suggest.coords
                  ? { top: suggest.coords.top + 2, left: Math.max(4, suggest.coords.left - 8) }
                  : { left: 0, bottom: -4, transform: 'translateY(100%)' }
              }
            >
              <div className="px-3 py-1 text-[10px] uppercase tracking-wider text-zinc-500 border-b border-zinc-800 bg-zinc-900">
                @{suggest.query || '…'}
              </div>
              {filteredOpponents.map((o, idx) => (
                <button
                  key={o.id}
                  type="button"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => applySuggestion(o)}
                  className={`w-full text-left px-3 py-2 text-sm flex items-center gap-2 ${
                    idx === suggest.highlighted ? 'bg-zinc-800' : 'hover:bg-zinc-900'
                  }`}
                >
                  <span className="font-mono text-rose-300">@{o.username}</span>
                  {o.name && o.name !== o.username && (
                    <span className="text-zinc-400 text-xs truncate">{o.name}</span>
                  )}
                  {o.played_against > 0 && (
                    <span className="ml-auto text-[10px] text-zinc-500">·{o.played_against}</span>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="mt-3 mb-2 text-xs uppercase tracking-wider text-zinc-500 flex items-center justify-between">
          <span>Превью</span>
          {parsing && <span className="text-amber-400 normal-case tracking-normal">парсим…</span>}
        </div>
        {error && (
          <p className="text-red-400 text-sm mb-3">{error}</p>
        )}
        {preview && preview.length > 0 && (
          <ul className="space-y-1 mb-3 text-sm">
            {preview.map((e) => (
              <li key={e.line_no} className={`px-2 py-1.5 rounded ${e.opponent_id ? 'bg-zinc-800/50' : 'bg-red-900/40'}`}>
                <span className="font-mono text-zinc-400 text-xs mr-2">L{e.line_no}</span>
                <span className="font-mono text-zinc-300 text-xs mr-2">{e.date.slice(0, 10)}</span>
                <span className="text-zinc-200 mr-2">{e.opponent_id ? e.opponent_name : `❓ ${e.opponent_raw}`}</span>
                {e.mode === 'aggregate' ? (
                  <span className="text-zinc-400 text-xs">агрегат {e.wins_a}:{e.wins_b}</span>
                ) : (
                  <span className="text-zinc-400 text-xs">{e.score_pairs.length} парт.</span>
                )}
              </li>
            ))}
          </ul>
        )}

        {unresolved.length > 0 && (
          <p className="text-amber-400 text-sm mb-3">
            ⚠ {unresolved.length} оппонент(ов) не распознано — поправь @username и пробуй снова.
          </p>
        )}

        <button
          onClick={submit}
          disabled={!canSubmit || submitting}
          className="w-full bg-gradient-to-br from-emerald-600 to-emerald-800 text-white py-3 rounded-xl font-semibold disabled:opacity-40"
        >
          {submitting ? 'Импортируем…' : `Импортировать ${preview?.length ? `(${preview.length})` : ''}`}
        </button>
      </SheetShell>
    </AnimatePresence>
  )
}

// ── SessionDetailsSheet ───────────────────────────────────────────────────────

export function SessionDetailsSheet({ sessionId, currentUserId, open, onClose, onDeleted }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [editIdx, setEditIdx] = useState(null)
  const { confirm, element: confirmEl } = useConfirmDialog()

  useEffect(() => {
    if (!open || !sessionId) return
    setError(null)
    tennisApi.getSession(sessionId)
      .then(setData)
      .catch((e) => setError(e.message || 'Не загрузилось'))
  }, [open, sessionId])

  const handleDeleteMatch = async (idx) => {
    const ok = await confirm({
      title: `Удалить партию #${idx + 1}?`,
      description: 'Партия исчезнет из сессии и статистики.',
      confirmLabel: 'Удалить',
      destructive: true,
    })
    if (!ok) return
    try {
      const updated = await tennisApi.deleteMatch(sessionId, idx)
      setData(updated)
    } catch (e) {
      setError(e.message || 'Ошибка')
    }
  }

  const handleEditMatch = async (a, b) => {
    if (editIdx == null) return
    try {
      const updated = await tennisApi.updateMatch(sessionId, editIdx, a, b)
      setData(updated)
      setEditIdx(null)
    } catch (e) {
      let msg = e.message || 'Ошибка'
      try { const p = JSON.parse(msg); if (p?.error) msg = p.error } catch { /* */ }
      setError(msg)
    }
  }

  const handleDeleteSession = async () => {
    const ok = await confirm({
      title: 'Удалить сессию?',
      description: 'Удалим целиком вместе со всеми партиями. Это нельзя отменить.',
      confirmLabel: 'Удалить',
      destructive: true,
    })
    if (!ok) return
    try {
      await tennisApi.deleteSession(sessionId)
      onDeleted()
    } catch (e) {
      let msg = e.message || 'Ошибка'
      try {
        const parsed = JSON.parse(msg)
        if (parsed?.error) msg = parsed.error
      } catch { /* */ }
      setError(msg)
    }
  }

  if (!open) return null

  return (
    <AnimatePresence>
      <SheetShell title={data ? `Сессия #${data.id}` : 'Сессия'} onClose={onClose}>
        {error && <p className="text-red-400 text-sm mb-3">{error}</p>}
        {!data && !error && <p className="text-zinc-500 text-sm">Загружаем…</p>}
        {data && (
          <>
            <div className="text-zinc-300 text-sm mb-1">
              {new Date(data.started_at).toLocaleString('ru-RU')}
            </div>
            <div className="text-white text-lg font-semibold mb-2">
              {data.player_a_name}{' '}
              <span className="font-mono">{data.wins[0]}:{data.wins[1]}</span>{' '}
              {data.player_b_name}
            </div>
            <div className="text-zinc-400 text-xs mb-4">
              {data.is_aggregate_only ? 'агрегатный импорт' : `${data.matches?.length ?? 0} партий`}
              {data.duration_seconds != null && ` · ${Math.round(data.duration_seconds / 60)} мин`}
              {data.closed_reason && ` · ${data.closed_reason}`}
            </div>

            {data.matches?.length > 0 && (
              <>
                <div className="text-xs uppercase tracking-wider text-zinc-500 mb-2 flex items-center justify-between">
                  <span>Партии</span>
                  {!data.can_edit_matches && data.ended_at && (
                    <span className="text-[10px] normal-case text-zinc-600">окно правки закрыто</span>
                  )}
                </div>
                <ol className="space-y-1 mb-4">
                  {data.matches.map((m, i) => {
                    const score = (m.score_a != null && m.score_b != null)
                      ? `${m.score_a}:${m.score_b}` : '—'
                    const winnerName = m.winner === 'a' ? data.player_a_name : data.player_b_name
                    const canEdit = data.can_edit_matches
                    return (
                      <li key={i} className="flex items-center justify-between bg-zinc-800/50 rounded px-3 py-2.5 text-sm">
                        <span className="text-zinc-500 w-6">#{i + 1}</span>
                        <span className="font-mono text-zinc-100 w-16">{score}</span>
                        <span className="text-zinc-400 text-xs flex-1 truncate ml-2">{winnerName}</span>
                        {canEdit && m.score_a != null && (
                          <button
                            onClick={() => setEditIdx(i)}
                            className="text-amber-300 hover:text-amber-200 ml-2 text-base px-1"
                            title="Поправить счёт"
                          >
                            ✏️
                          </button>
                        )}
                        {canEdit && (
                          <button
                            onClick={() => handleDeleteMatch(i)}
                            className="text-red-400 hover:text-red-300 ml-2 text-base px-1"
                            title="Удалить партию"
                          >
                            🗑
                          </button>
                        )}
                      </li>
                    )
                  })}
                </ol>
              </>
            )}

            {data.initiator_id === currentUserId && (
              <button
                onClick={handleDeleteSession}
                className="w-full bg-red-900/60 hover:bg-red-900 text-red-100 py-2.5 rounded-xl text-sm"
              >
                🗑 Удалить сессию целиком
              </button>
            )}
          </>
        )}
        {confirmEl}
        <AnimatePresence>
          {editIdx != null && data?.matches?.[editIdx] && (
            <EditMatchSheet
              open
              nameA={data.player_a_name}
              nameB={data.player_b_name}
              initialScoreA={data.matches[editIdx].score_a}
              initialScoreB={data.matches[editIdx].score_b}
              onSave={handleEditMatch}
              onClose={() => setEditIdx(null)}
            />
          )}
        </AnimatePresence>
      </SheetShell>
    </AnimatePresence>
  )
}

// ── StatsSheet ────────────────────────────────────────────────────────────────

function fmtDuration(s) {
  if (s == null) return '—'
  if (s < 60) return `${Math.round(s)}с`
  if (s < 3600) return `${Math.round(s / 60)} мин`
  return `${(s / 3600).toFixed(1)} ч`
}

export function StatsSheet({ open, onClose }) {
  const [stats, setStats] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!open) return
    setError(null)
    tennisApi.getStats()
      .then(setStats)
      .catch((e) => setError(e.message || 'Не загрузилось'))
  }, [open])

  if (!open) return null
  return (
    <AnimatePresence>
      <SheetShell title="Моя статистика" onClose={onClose}>
        {error && <p className="text-red-400 text-sm">{error}</p>}
        {!stats && !error && <p className="text-zinc-500 text-sm">Загружаем…</p>}
        {stats && (
          <div className="space-y-3">
            {stats.matches === 0 ? (
              <p className="text-zinc-400 text-sm">Партий пока нет.</p>
            ) : (
              <>
                <div className="grid grid-cols-2 gap-3">
                  <StatCard label="Сессий" value={stats.sessions} />
                  <StatCard label="Партий" value={stats.matches} />
                  <StatCard label="Победы / Поражения" value={`${stats.wins} / ${stats.losses}`} />
                  <StatCard label="Win-rate" value={`${Math.round(stats.win_rate * 100)}%`} accent />
                  <StatCard label="Серия побед (max)" value={stats.longest_win_streak} />
                  <StatCard label="Партий за сессию (медиана)" value={stats.median_matches_per_session ?? '—'} />
                  <StatCard label="Разница очков (медиана)" value={stats.median_point_diff ?? '—'} />
                  <StatCard label="Партия (медиана)" value={fmtDuration(stats.median_match_duration_s)} />
                </div>
              </>
            )}
          </div>
        )}
      </SheetShell>
    </AnimatePresence>
  )
}

function StatCard({ label, value, accent = false }) {
  return (
    <div className={`bg-zinc-800/60 rounded-xl px-3 py-3 border ${accent ? 'border-rose-700' : 'border-zinc-800'}`}>
      <div className="text-zinc-400 text-[10px] uppercase tracking-wider">{label}</div>
      <div className="text-white text-xl font-semibold mt-1 tabular-nums">{value}</div>
    </div>
  )
}
