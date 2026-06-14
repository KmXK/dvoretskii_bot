import { useCallback, useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ChevronLeft, ChevronDown, Plus, X, Users, Mic, Square, Image as ImageIcon,
  Type, Sparkles, Loader2, Check, Trash2, Crown,
} from 'lucide-react'
import { api } from '../api/client'

// Создание счёта с нуля прямо в мини-аппе: шаг «люди» (собрать → подтвердить
// состав + кто платил) → шаг «позиции» (голос/фото/текст → AI-разбор, ручная
// правка, плательщик по позиции) → доска распределения.

function pickAudioMime() {
  if (typeof MediaRecorder === 'undefined') return null
  const prefs = ['audio/ogg;codecs=opus', 'audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']
  for (const m of prefs) {
    try { if (MediaRecorder.isTypeSupported(m)) return m } catch { /* noop */ }
  }
  return ''
}

const UNKNOWN_PID = '__unknown__'
const curSymbol = (c) => (c === 'BYN' ? 'р' : c)

// ── Кастомный дропдаун «кто платил» ───────────────────────────────────────────

function PayerSelect({ value, options, onChange, placeholder = 'кто платил', className = '', compact = false }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [open])
  const current = options.find((o) => o.id === value)
  return (
    <div className={`relative ${className}`} ref={ref}>
      {compact ? (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-spotify-text hover:text-white hover:bg-white/5 transition max-w-full"
          title="кто платил"
        >
          <Crown size={12} className="shrink-0 text-gold/80" />
          <span className="truncate">{current?.name || placeholder}</span>
        </button>
      ) : (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="w-full inline-flex items-center justify-between gap-1 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 px-2.5 py-1.5 text-xs text-white transition"
        >
          <span className={`truncate ${current ? '' : 'text-spotify-text/70'}`}>{current?.name || placeholder}</span>
          <ChevronDown size={13} className="shrink-0 opacity-70" />
        </button>
      )}
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.97 }}
            transition={{ duration: 0.12 }}
            className="absolute right-0 mt-1 z-30 min-w-[150px] max-h-52 overflow-y-auto rounded-xl bg-spotify-gray border border-white/10 shadow-xl shadow-black/50 py-1"
          >
            {options.map((o) => (
              <button
                key={o.id}
                type="button"
                onClick={() => { onChange(o.id); setOpen(false) }}
                className="w-full flex items-center justify-between gap-2 px-3 py-2 text-left text-sm text-white hover:bg-white/10 transition"
              >
                <span className="truncate">{o.name}</span>
                {o.id === value && <Check size={14} className="text-spotify-green shrink-0" />}
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

// ── Step 1: люди (собрать → подтвердить) ───────────────────────────────────────

function PeopleStep({ onCancel, onNext }) {
  const [stage, setStage] = useState('pick') // 'pick' | 'confirm'
  const [name, setName] = useState('')
  const [circle, setCircle] = useState([])
  const [selected, setSelected] = useState(() => new Set())
  const [manual, setManual] = useState([])
  const [manualRaw, setManualRaw] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  // Подтверждающий состав (резолв с бэка) + выбранный плательщик.
  const [roster, setRoster] = useState([]) // [{id, display_name, username}], автор первым
  const [payerId, setPayerId] = useState(null)

  useEffect(() => {
    api.get('/api/bills/circle')
      .then((d) => setCircle(d.people || []))
      .catch(() => { /* окружение не критично */ })
  }, [])

  const toggle = (id) => setSelected((prev) => {
    const next = new Set(prev)
    next.has(id) ? next.delete(id) : next.add(id)
    return next
  })

  const addManual = () => {
    const raw = manualRaw.trim()
    if (!raw) return
    if (!manual.includes(raw)) setManual((m) => [...m, raw])
    setManualRaw('')
  }

  // pick → confirm: резолвим весь состав в реальные id (автор добавится на бэке).
  const goConfirm = async () => {
    setError(null)
    if (!name.trim()) { setError('Дай счёту название'); return }
    const participants = [
      ...[...selected].map((id) => ({ person_id: id })),
      ...manual.map((raw) => (raw.startsWith('@') ? { username: raw } : { name: raw })),
    ]
    setBusy(true)
    try {
      const data = await api.post('/api/bills/resolve-people', { participants })
      const people = data.people || []
      setRoster(people)
      setPayerId((prev) => prev || people[0]?.id || null)
      setStage('confirm')
    } catch (e) {
      setError(e.message || 'Не удалось собрать состав')
    } finally {
      setBusy(false)
    }
  }

  const removeFromRoster = (id) => {
    setRoster((r) => r.filter((p) => p.id !== id))
    setPayerId((p) => (p === id ? roster[0]?.id || null : p))
  }

  // confirm → создать счёт + назначить плательщика, перейти к позициям.
  const create = async () => {
    setError(null)
    setBusy(true)
    try {
      const bill = await api.post('/api/bills', {
        name: name.trim(), draft: true,
        participants: roster.map((p) => ({ person_id: p.id })),
      })
      if (payerId) {
        try { await api.put(`/api/bills/${bill.id}/creditor`, { person_id: payerId }) } catch { /* не критично */ }
      }
      onNext(bill, payerId)
    } catch (e) {
      setError(e.message || 'Не удалось создать счёт')
    } finally {
      setBusy(false)
    }
  }

  // ── вид «подтвердить состав» ──
  if (stage === 'confirm') {
    return (
      <motion.div initial={{ opacity: 0, x: 16 }} animate={{ opacity: 1, x: 0 }} className="px-4 pt-6 pb-4">
        <div className="flex items-center gap-2 mb-1">
          <button onClick={() => setStage('pick')} className="text-spotify-text hover:text-white p-1 -ml-1"><ChevronLeft size={22} /></button>
          <h1 className="font-display text-2xl font-extrabold text-white truncate">{name.trim()}</h1>
        </div>
        <p className="text-spotify-text text-sm mb-5 pl-8">Проверь состав и выбери, кто платил</p>

        <div className="text-xs uppercase tracking-wider text-spotify-text mb-2">Участники ({roster.length})</div>
        <div className="space-y-2 mb-5">
          {roster.map((p, i) => {
            const isAuthor = i === 0
            const isPayer = payerId === p.id
            return (
              <motion.div
                key={p.id}
                layout
                initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                className={`flex items-center gap-2 rounded-xl px-3 py-2.5 border transition-colors ${
                  isPayer ? 'bg-spotify-green/15 border-spotify-green/50' : 'bg-spotify-dark border-white/10'
                }`}
              >
                <button
                  onClick={() => setPayerId(p.id)}
                  className={`shrink-0 w-7 h-7 rounded-full inline-flex items-center justify-center border transition-colors ${
                    isPayer ? 'bg-spotify-green/30 border-spotify-green text-spotify-green' : 'border-white/20 text-spotify-text hover:border-white/40'
                  }`}
                  title="кто платил"
                >
                  <Crown size={14} className={isPayer ? 'fill-current' : ''} />
                </button>
                <div className="min-w-0 flex-1">
                  <div className="text-white text-sm truncate inline-flex items-center gap-1.5">
                    {p.display_name}
                    {isAuthor && <span className="text-[10px] px-1.5 py-0.5 rounded bg-gold/20 text-gold">ты</span>}
                  </div>
                  {p.username && <div className="text-[11px] text-spotify-text truncate">@{p.username}</div>}
                </div>
                {!isAuthor && (
                  <button onClick={() => removeFromRoster(p.id)} className="shrink-0 text-spotify-text/70 hover:text-red-400 p-1">
                    <X size={16} />
                  </button>
                )}
              </motion.div>
            )
          })}
        </div>

        <p className="text-spotify-text/70 text-[11px] mb-4 inline-flex items-center gap-1">
          <Crown size={11} /> корона = кто заплатил за счёт (можно поменять у позиций потом)
        </p>

        {error && <div className="text-red-400 text-sm mb-3">{error}</div>}

        <motion.button
          whileTap={{ scale: 0.98 }}
          onClick={create}
          disabled={busy}
          className="w-full rounded-2xl py-4 font-bold text-base bg-gold text-black disabled:opacity-60 inline-flex items-center justify-center gap-2"
        >
          {busy ? <Loader2 size={18} className="animate-spin" /> : <>Дальше — позиции <ChevronLeft size={18} className="rotate-180" /></>}
        </motion.button>
      </motion.div>
    )
  }

  // ── вид «собрать людей» ──
  return (
    <motion.div initial={{ opacity: 0, x: 16 }} animate={{ opacity: 1, x: 0 }} className="px-4 pt-6 pb-4">
      <div className="flex items-center gap-2 mb-5">
        <button onClick={onCancel} className="text-spotify-text hover:text-white p-1 -ml-1"><ChevronLeft size={22} /></button>
        <h1 className="font-display text-2xl font-extrabold text-white">Новый счёт</h1>
      </div>

      <input
        autoFocus
        placeholder="Название счёта…"
        value={name}
        onChange={(e) => setName(e.target.value)}
        className="w-full rounded-xl bg-spotify-gray px-4 py-3 text-white text-base outline-none focus:ring-2 focus:ring-gold/50 transition mb-5"
      />

      <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-spotify-text mb-2">
        <Users size={14} /> Кто участвует
      </div>

      <div className="mb-3 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-gold/15 border border-gold/40 text-gold text-sm">
        <Crown size={13} /> Ты <span className="opacity-60 text-[11px]">— уже в счёте</span>
      </div>

      {circle.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-3">
          {circle.slice(0, 24).map((p) => {
            const active = selected.has(p.id)
            return (
              <motion.button
                key={p.id}
                whileTap={{ scale: 0.94 }}
                onClick={() => toggle(p.id)}
                className={`px-3 py-1.5 rounded-full text-sm border transition-colors ${
                  active
                    ? 'bg-gold text-black border-gold font-medium'
                    : 'bg-white/5 border-white/10 text-spotify-text hover:bg-white/10'
                }`}
              >
                {p.name}
                {p.count > 0 && <span className="ml-1 text-[10px] opacity-60">·{p.count}</span>}
              </motion.button>
            )
          })}
        </div>
      )}

      <AnimatePresence>
        {manual.length > 0 && (
          <motion.div
            initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }}
            className="flex flex-wrap gap-2 mb-3"
          >
            {manual.map((raw) => (
              <span key={raw} className="px-3 py-1.5 rounded-full text-sm bg-indigo-soft border border-indigo/50 text-indigo inline-flex items-center gap-1">
                {raw}
                <button onClick={() => setManual((m) => m.filter((x) => x !== raw))} className="opacity-70 hover:opacity-100"><X size={13} /></button>
              </span>
            ))}
          </motion.div>
        )}
      </AnimatePresence>

      <div className="flex gap-2 mb-2">
        <input
          placeholder="Имя или @username…"
          value={manualRaw}
          onChange={(e) => setManualRaw(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && addManual()}
          className="flex-1 rounded-lg bg-white/5 px-3 py-2.5 text-sm text-white placeholder:text-spotify-text/60 outline-none focus:bg-white/10 transition"
        />
        <button onClick={addManual} className="px-3 rounded-lg bg-white/5 text-spotify-text hover:bg-white/10 transition"><Plus size={18} /></button>
      </div>
      <p className="text-spotify-text/70 text-[11px] mb-5">На следующем шаге проверишь состав и выберешь, кто платил.</p>

      {error && <div className="text-red-400 text-sm mb-3">{error}</div>}

      <motion.button
        whileTap={{ scale: 0.98 }}
        onClick={goConfirm}
        disabled={busy}
        className="w-full rounded-2xl py-4 font-bold text-base bg-gold text-black disabled:opacity-60 inline-flex items-center justify-center gap-2"
      >
        {busy ? <Loader2 size={18} className="animate-spin" /> : <>Проверить состав <ChevronLeft size={18} className="rotate-180" /></>}
      </motion.button>
    </motion.div>
  )
}

// ── Step 2: позиции ───────────────────────────────────────────────────────────

const KIND_LABEL = { 'Текст': Type, 'Фото': ImageIcon, 'Голосовое': Mic }

function contextKind(chunk) {
  const m = /^\[(Текст|Фото|Голосовое)\]/.exec(chunk || '')
  return m ? m[1] : 'Текст'
}

// Инлайн-редактируемое значение (название/кол-во/цена) с сохранением на blur/enter.
function EditableCell({ value, onSave, className = '', type = 'text', placeholder = '' }) {
  const [v, setV] = useState(String(value ?? ''))
  const [prev, setPrev] = useState(value)
  if (value !== prev) { setPrev(value); setV(String(value ?? '')) } // sync при внешнем изменении
  const commit = () => { if (v !== String(value ?? '')) onSave(v) }
  return (
    <input
      value={v}
      type={type}
      inputMode={type === 'number' ? 'decimal' : undefined}
      placeholder={placeholder}
      onChange={(e) => setV(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }}
      className={`bg-transparent outline-none focus:bg-white/5 rounded px-1.5 py-1 transition ${className}`}
    />
  )
}

export function PositionsStep({ bill, defaultPayer, onBack, onReady, onDeleted }) {
  const [chunks, setChunks] = useState(() => bill.collection_context || [])
  const [positions, setPositions] = useState(() => bill.transactions || [])
  const [participantIds, setParticipantIds] = useState(() => bill.participants || [])
  const [namesById, setNamesById] = useState({})
  const [payerId, setPayerId] = useState(() => defaultPayer || bill.author_person_id)
  const [textVal, setTextVal] = useState('')
  const [recording, setRecording] = useState(false)
  const [seconds, setSeconds] = useState(0)
  const [uploading, setUploading] = useState(null) // 'Фото' | 'Голосовое' | 'Текст'
  const [parsing, setParsing] = useState(false)
  const [error, setError] = useState(null)
  const [questions, setQuestions] = useState([])
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [adding, setAdding] = useState(false)
  const [newItem, setNewItem] = useState({ name: '', price: '', qty: '1' })

  const recRef = useRef(null)
  const streamRef = useRef(null)
  const fileRef = useRef(null)
  const timerRef = useRef(null)

  const cur = curSymbol(bill.currency)

  const payerOptions = participantIds
    .map((pid) => ({ id: pid, name: namesById[pid] || '…' }))
    .concat([{ id: UNKNOWN_PID, name: '— не указан' }])

  const loadNames = useCallback(async () => {
    try {
      const persons = await api.get('/api/bills/persons')
      setNamesById(Object.fromEntries((persons || []).map((p) => [p.id, p.display_name])))
    } catch { /* имена не критичны */ }
  }, [])

  useEffect(() => { loadNames() }, [loadNames])

  // Назначить одного плательщика на весь счёт (дефолт для всех позиций).
  const applyPayer = useCallback(async (pid) => {
    setPayerId(pid)
    try {
      const updated = await api.put(`/api/bills/${bill.id}/creditor`, { person_id: pid })
      setPositions(updated.transactions || [])
      setParticipantIds(updated.participants || [])
    } catch (e) {
      setError(e.message || 'Не удалось назначить плательщика')
    }
  }, [bill.id])

  const patchTx = useCallback(async (txId, patch) => {
    setPositions((prev) => prev.map((t) => (t.id === txId ? { ...t, ...patch } : t)))
    try {
      const updated = await api.patch(`/api/bills/${bill.id}/transactions/${txId}`, patch)
      setPositions((prev) => prev.map((t) => (t.id === txId ? updated : t)))
    } catch (e) {
      setError(e.message || 'Не удалось сохранить')
    }
  }, [bill.id])

  const deleteTx = useCallback(async (txId) => {
    setPositions((prev) => prev.filter((t) => t.id !== txId))
    try { await api.delete(`/api/bills/${bill.id}/transactions/${txId}`) }
    catch (e) { setError(e.message || 'Не удалось удалить') }
  }, [bill.id])

  const addItem = useCallback(async () => {
    const name = newItem.name.trim()
    const price = Math.round(parseFloat((newItem.price || '').replace(',', '.')) * 100)
    const qty = Math.max(1, parseInt(newItem.qty, 10) || 1)
    if (!name || !price || price <= 0) { setError('Название и цена обязательны'); return }
    setError(null)
    try {
      const tx = await api.post(`/api/bills/${bill.id}/transactions`, {
        item_name: name, unit_price_minor: price, quantity: qty,
        creditor: payerId || UNKNOWN_PID, assignments: [],
      })
      setPositions((prev) => [...prev, tx])
      setNewItem({ name: '', price: '', qty: '1' })
      setAdding(false)
    } catch (e) {
      setError(e.message || 'Не удалось добавить позицию')
    }
  }, [bill.id, newItem, payerId])

  const removeBill = useCallback(async () => {
    try {
      await api.delete(`/api/bills/${bill.id}`)
      onDeleted()
    } catch (e) {
      setError(e.message || 'Не удалось удалить счёт')
      setConfirmDelete(false)
    }
  }, [bill.id, onDeleted])

  const post = useCallback(async (fd) => {
    const data = await api.post(`/api/bills/${bill.id}/collect`, fd)
    setChunks((c) => [...c, data.recognized
      ? `[${data.kind === 'photo' ? 'Фото' : data.kind === 'voice' ? 'Голосовое' : 'Текст'}]\n${data.recognized}`
      : `[?]`])
    return data
  }, [bill.id])

  const addText = async () => {
    const v = textVal.trim()
    if (!v) return
    setError(null); setUploading('Текст')
    const fd = new FormData()
    fd.append('kind', 'text')
    fd.append('text', v)
    try { await post(fd); setTextVal('') }
    catch (e) { setError(e.message || 'Не вышло') }
    finally { setUploading(null) }
  }

  const onPhoto = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setError(null); setUploading('Фото')
    const fd = new FormData()
    fd.append('kind', 'photo')
    fd.append('file', file, file.name || 'photo.jpg')
    try { await post(fd) }
    catch (err) { setError(err.message || 'Не удалось распознать фото') }
    finally { setUploading(null) }
  }

  const uploadVoice = async (blob, ext) => {
    setError(null); setUploading('Голосовое')
    const fd = new FormData()
    fd.append('kind', 'voice')
    fd.append('file', blob, `voice.${ext}`)
    try { await post(fd) }
    catch (err) { setError(err.message || 'Речь не распознана') }
    finally { setUploading(null) }
  }

  const startRec = async () => {
    setError(null)
    const mime = pickAudioMime()
    if (mime === null || !navigator.mediaDevices?.getUserMedia) {
      fileRef.current?.click()
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      const mr = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
      const parts = []
      mr.ondataavailable = (ev) => ev.data.size && parts.push(ev.data)
      mr.onstop = () => {
        const type = mr.mimeType || 'audio/webm'
        const ext = type.includes('ogg') ? 'ogg' : type.includes('mp4') ? 'm4a' : 'webm'
        uploadVoice(new Blob(parts, { type }), ext)
        streamRef.current?.getTracks().forEach((t) => t.stop())
        streamRef.current = null
      }
      recRef.current = mr
      mr.start()
      setRecording(true)
      setSeconds(0)
      timerRef.current = setInterval(() => setSeconds((s) => s + 1), 1000)
    } catch {
      setError('Нет доступа к микрофону — приложи аудиофайл')
      fileRef.current?.click()
    }
  }

  const stopRec = () => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
    setRecording(false)
    try { recRef.current?.stop() } catch { /* noop */ }
  }

  useEffect(() => () => {
    if (timerRef.current) clearInterval(timerRef.current)
    streamRef.current?.getTracks().forEach((t) => t.stop())
  }, [])

  const onAudioFile = (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    const ext = (file.name.split('.').pop() || 'ogg').toLowerCase()
    uploadVoice(file, ext)
  }

  const runParse = async () => {
    setError(null); setParsing(true); setQuestions([])
    try {
      const data = await api.post(`/api/bills/${bill.id}/parse`, { payer_person_id: payerId || bill.author_person_id })
      const txs = data.bill?.transactions || []
      setPositions(txs)
      setParticipantIds(data.bill?.participants || [])
      setQuestions(data.questions || [])
      await loadNames()
      // По умолчанию весь счёт оплачивает выбранный на шаге 1 плательщик.
      await applyPayer(payerId || bill.author_person_id)
    } catch (e) {
      setError(e.message || 'Не нашёл позиций — добавь ещё контекста')
    } finally {
      setParsing(false)
    }
  }

  const fmtTime = (s) => `${String(Math.floor(s / 60)).padStart(1, '0')}:${String(s % 60).padStart(2, '0')}`

  return (
    <motion.div initial={{ opacity: 0, x: 16 }} animate={{ opacity: 1, x: 0 }} className="px-4 pt-6 pb-4">
      <div className="flex items-center gap-2 mb-1">
        <button onClick={onBack} className="text-spotify-text hover:text-white p-1 -ml-1"><ChevronLeft size={22} /></button>
        <h1 className="font-display text-2xl font-extrabold text-white truncate flex-1">{bill.name}</h1>
        <button onClick={() => setConfirmDelete(true)} className="text-spotify-text/70 hover:text-red-400 p-1" title="Удалить счёт">
          <Trash2 size={19} />
        </button>
      </div>
      <p className="text-spotify-text text-sm mb-5 pl-8">Надиктуй, сфоткай чек или впиши позиции</p>

      {/* собранные куски контекста */}
      <AnimatePresence>
        {chunks.length > 0 && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="flex flex-wrap gap-2 mb-4"
          >
            {chunks.map((c, i) => {
              const k = contextKind(c)
              const Icon = KIND_LABEL[k] || Type
              return (
                <motion.span
                  key={i}
                  initial={{ scale: 0.6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
                  className="px-3 py-1.5 rounded-full text-xs bg-spotify-green/15 border border-spotify-green/30 text-spotify-green inline-flex items-center gap-1.5"
                >
                  <Icon size={12} /> {k}
                </motion.span>
              )
            })}
          </motion.div>
        )}
      </AnimatePresence>

      {/* ввод: текст */}
      <div className="flex gap-2 mb-3">
        <input
          placeholder="Например: пицца 30, кола 5, платил я…"
          value={textVal}
          onChange={(e) => setTextVal(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && addText()}
          className="flex-1 rounded-lg bg-white/5 px-3 py-2.5 text-sm text-white placeholder:text-spotify-text/60 outline-none focus:bg-white/10 transition"
        />
        <button onClick={addText} disabled={!textVal.trim() || uploading === 'Текст'} className="px-3 rounded-lg bg-white/5 text-spotify-text hover:bg-white/10 disabled:opacity-50 transition">
          {uploading === 'Текст' ? <Loader2 size={18} className="animate-spin" /> : <Plus size={18} />}
        </button>
      </div>

      {/* ввод: фото + голос */}
      <div className="grid grid-cols-2 gap-2 mb-5">
        <button
          onClick={() => document.getElementById('bill-photo-input')?.click()}
          disabled={!!uploading}
          className="rounded-xl bg-white/5 hover:bg-white/10 py-3 text-sm text-white inline-flex items-center justify-center gap-2 disabled:opacity-50 transition"
        >
          {uploading === 'Фото' ? <Loader2 size={16} className="animate-spin" /> : <ImageIcon size={16} />} Фото чека
        </button>
        <input id="bill-photo-input" type="file" accept="image/*" className="hidden" onChange={onPhoto} />
        <input ref={fileRef} type="file" accept="audio/*" className="hidden" onChange={onAudioFile} />

        {!recording ? (
          <button
            onClick={startRec}
            disabled={!!uploading}
            className="rounded-xl bg-gold/15 hover:bg-gold/25 border border-gold/40 py-3 text-sm text-gold inline-flex items-center justify-center gap-2 disabled:opacity-50 transition"
          >
            {uploading === 'Голосовое' ? <Loader2 size={16} className="animate-spin" /> : <Mic size={16} />} Записать голос
          </button>
        ) : (
          <motion.button
            onClick={stopRec}
            initial={{ scale: 0.96 }}
            animate={{ scale: [1, 1.04, 1] }}
            transition={{ repeat: Infinity, duration: 1.1 }}
            className="rounded-xl bg-red-500/20 border border-red-500/50 py-3 text-sm text-red-300 inline-flex items-center justify-center gap-2"
          >
            <Square size={14} className="fill-current" /> Стоп · {fmtTime(seconds)}
          </motion.button>
        )}
      </div>

      {error && <div className="text-red-400 text-sm mb-3">{error}</div>}

      {/* распознать */}
      <motion.button
        whileTap={{ scale: 0.98 }}
        onClick={runParse}
        disabled={parsing || chunks.length === 0}
        className="w-full rounded-2xl py-3.5 font-bold text-base bg-indigo text-white disabled:opacity-50 inline-flex items-center justify-center gap-2 mb-4"
      >
        {parsing ? <><Loader2 size={18} className="animate-spin" /> Разбираю…</> : <><Sparkles size={18} /> Распознать позиции</>}
      </motion.button>

      {questions.length > 0 && (
        <div className="mb-4 rounded-xl bg-yellow-500/10 border border-yellow-500/25 p-3 text-sm text-yellow-200/90 space-y-1">
          <div className="font-medium">Уточни и допиши контекстом:</div>
          {questions.map((q, i) => <div key={i}>• {q.text}</div>)}
        </div>
      )}

      {/* кто платил — дефолт на весь счёт */}
      {positions.length > 0 && (
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="mb-4">
          <div className="text-xs uppercase tracking-wider text-spotify-text mb-2">Кто платил за всё</div>
          <div className="flex flex-wrap gap-2">
            {participantIds.map((pid) => {
              const active = payerId === pid
              return (
                <motion.button
                  key={pid}
                  whileTap={{ scale: 0.94 }}
                  onClick={() => applyPayer(pid)}
                  className={`px-3 py-1.5 rounded-full text-sm border transition-colors ${
                    active
                      ? 'bg-spotify-green/25 border-spotify-green/60 text-spotify-green font-medium'
                      : 'bg-white/5 border-white/10 text-spotify-text hover:bg-white/10'
                  }`}
                >
                  {namesById[pid] || '…'}
                </motion.button>
              )
            })}
          </div>
        </motion.div>
      )}

      {/* редактируемые позиции */}
      {positions.length > 0 && (
        <div className="space-y-2 mb-3">
          <div className="text-xs uppercase tracking-wider text-spotify-text">Позиции ({positions.length})</div>
          {positions.map((tx) => (
            <motion.div
              key={tx.id}
              layout
              initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
              className="bg-spotify-dark rounded-lg p-2.5"
            >
              <div className="flex items-center gap-2">
                <EditableCell
                  value={tx.item_name}
                  placeholder="Название"
                  onSave={(v) => patchTx(tx.id, { item_name: v })}
                  className="flex-1 text-white text-sm min-w-0"
                />
                <button onClick={() => deleteTx(tx.id)} className="shrink-0 text-spotify-text/60 hover:text-red-400 p-1">
                  <X size={15} />
                </button>
              </div>
              <div className="flex items-center gap-2 mt-1.5">
                <div className="inline-flex items-center text-spotify-text text-xs">
                  <EditableCell
                    value={tx.quantity}
                    type="number"
                    onSave={(v) => patchTx(tx.id, { quantity: Math.max(1, parseInt(v, 10) || 1) })}
                    className="w-10 text-center text-white tabular-nums"
                  />
                  <span className="opacity-60">×</span>
                </div>
                <div className="inline-flex items-center text-spotify-text text-xs">
                  <EditableCell
                    value={(tx.unit_price_minor / 100).toFixed(2).replace(/\.00$/, '')}
                    type="number"
                    onSave={(v) => patchTx(tx.id, { unit_price_minor: Math.max(0, Math.round(parseFloat((v || '').replace(',', '.')) * 100) || 0) })}
                    className="w-16 text-right text-white tabular-nums"
                  />
                  <span className="opacity-60 ml-1">{cur}</span>
                </div>
                <PayerSelect
                  value={tx.creditor}
                  options={payerOptions}
                  onChange={(pid) => patchTx(tx.id, { creditor: pid })}
                  className="ml-auto"
                  placeholder="кто платил"
                  compact
                />
              </div>
            </motion.div>
          ))}
        </div>
      )}

      {/* добавить позицию вручную */}
      {(positions.length > 0 || chunks.length === 0) && (
        adding ? (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} className="bg-spotify-dark rounded-lg p-2.5 mb-5 space-y-2">
            <input
              autoFocus
              placeholder="Название позиции"
              value={newItem.name}
              onChange={(e) => setNewItem((n) => ({ ...n, name: e.target.value }))}
              className="w-full bg-white/5 rounded px-2.5 py-1.5 text-white text-sm outline-none focus:bg-white/10"
            />
            <div className="flex items-center gap-2">
              <input
                placeholder="кол-во" inputMode="numeric"
                value={newItem.qty}
                onChange={(e) => setNewItem((n) => ({ ...n, qty: e.target.value }))}
                className="w-16 bg-white/5 rounded px-2.5 py-1.5 text-white text-sm text-center tabular-nums outline-none focus:bg-white/10"
              />
              <span className="text-spotify-text text-xs">×</span>
              <input
                placeholder="цена" inputMode="decimal"
                value={newItem.price}
                onChange={(e) => setNewItem((n) => ({ ...n, price: e.target.value }))}
                className="w-20 bg-white/5 rounded px-2.5 py-1.5 text-white text-sm text-right tabular-nums outline-none focus:bg-white/10"
              />
              <span className="text-spotify-text text-xs">{cur}</span>
              <button onClick={addItem} className="ml-auto px-3 py-1.5 rounded-lg bg-gold text-black text-sm font-medium inline-flex items-center gap-1"><Check size={15} /></button>
              <button onClick={() => { setAdding(false); setNewItem({ name: '', price: '', qty: '1' }) }} className="px-2.5 py-1.5 rounded-lg bg-white/5 text-spotify-text"><X size={15} /></button>
            </div>
          </motion.div>
        ) : (
          <button
            onClick={() => setAdding(true)}
            className="w-full rounded-lg border border-dashed border-white/15 text-spotify-text hover:text-white hover:border-white/30 py-2.5 text-sm inline-flex items-center justify-center gap-1.5 mb-5 transition"
          >
            <Plus size={16} /> Добавить позицию вручную
          </button>
        )
      )}

      {positions.length > 0 && (
        <motion.button
          whileTap={{ scale: 0.98 }}
          onClick={() => onReady(bill.id)}
          className="w-full rounded-2xl py-4 font-bold text-base bg-gold text-black inline-flex items-center justify-center gap-2"
        >
          Распределить по людям <ChevronLeft size={18} className="rotate-180" />
        </motion.button>
      )}

      {/* подтверждение удаления */}
      <AnimatePresence>
        {confirmDelete && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4"
            onClick={() => setConfirmDelete(false)}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }}
              onClick={(e) => e.stopPropagation()}
              className="bg-spotify-black rounded-2xl p-5 w-full max-w-sm"
            >
              <h3 className="text-white font-bold text-lg mb-1">Удалить счёт?</h3>
              <p className="text-spotify-text text-sm mb-4">«{bill.name}» удалится целиком. Это не отменить.</p>
              <div className="flex gap-2">
                <button onClick={() => setConfirmDelete(false)} className="flex-1 bg-spotify-gray text-white rounded-xl py-2.5">Отмена</button>
                <button onClick={removeBill} className="flex-1 bg-red-500/90 text-white rounded-xl py-2.5 font-medium inline-flex items-center justify-center gap-1.5"><Trash2 size={16} /> Удалить</button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

// ── Wizard ────────────────────────────────────────────────────────────────────

export default function BillCreate({ onCancel, onReady }) {
  const [bill, setBill] = useState(null)
  const [payer, setPayer] = useState(null)
  return (
    <div className="max-w-3xl mx-auto">
      <AnimatePresence mode="wait">
        {!bill ? (
          <PeopleStep key="people" onCancel={onCancel} onNext={(b, p) => { setBill(b); setPayer(p) }} />
        ) : (
          <PositionsStep
            key="positions"
            bill={bill}
            defaultPayer={payer}
            onBack={() => setBill(null)}
            onReady={onReady}
            onDeleted={onCancel}
          />
        )}
      </AnimatePresence>
    </div>
  )
}
