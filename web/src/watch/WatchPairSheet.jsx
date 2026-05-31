import { useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import confetti from 'canvas-confetti'
import { SheetShell } from '../tennis/Modals'
import { useConfirmDialog } from '../tennis/ConfirmDialog'
import { useToast } from '../context/useToast'
import { watchApi } from './api'

const POLL_MS = 3500

function relTime(iso) {
  if (!iso) return 'ещё не выходило на связь'
  const then = new Date(iso).getTime()
  const diff = Date.now() - then
  if (Number.isNaN(diff)) return ''
  const min = Math.floor(diff / 60000)
  if (min < 1) return 'только что'
  if (min < 60) return `${min} мин назад`
  const hrs = Math.floor(min / 60)
  if (hrs < 24) return `${hrs} ч назад`
  return `${Math.floor(hrs / 24)} дн назад`
}

function CodeBlock({ code, ttl, onRefresh, refreshing }) {
  const [remaining, setRemaining] = useState(ttl)
  const expiresAtRef = useRef(Date.now() + ttl * 1000)

  // Сбрасываем таймер при каждом новом коде
  useEffect(() => {
    expiresAtRef.current = Date.now() + ttl * 1000
    setRemaining(ttl)
    const id = window.setInterval(() => {
      const left = Math.max(0, Math.round((expiresAtRef.current - Date.now()) / 1000))
      setRemaining(left)
      if (left <= 0) window.clearInterval(id)
    }, 250)
    return () => window.clearInterval(id)
  }, [code, ttl])

  const expired = remaining <= 0
  const pct = Math.max(0, Math.min(1, remaining / ttl))
  const mm = String(Math.floor(remaining / 60)).padStart(1, '0')
  const ss = String(remaining % 60).padStart(2, '0')

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code)
    } catch { /* clipboard may be blocked in webview — код и так на экране */ }
  }

  return (
    <div className="relative rounded-2xl bg-gradient-to-br from-indigo-700/30 to-zinc-900 border border-indigo-800/60 px-5 py-6 mb-5 overflow-hidden">
      <div className="text-[11px] uppercase tracking-wider text-indigo-300/80 mb-3 text-center">
        Введи код на часах
      </div>

      <AnimatePresence mode="wait">
        <motion.button
          key={code}
          type="button"
          onClick={copy}
          initial={{ opacity: 0, y: 8, filter: 'blur(6px)' }}
          animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
          exit={{ opacity: 0, y: -8, filter: 'blur(6px)' }}
          transition={{ type: 'spring', stiffness: 400, damping: 26 }}
          whileTap={{ scale: 0.97 }}
          className={`block w-full text-center font-mono font-black tracking-[0.3em] text-white tabular-nums ${
            expired ? 'opacity-30' : ''
          }`}
          style={{ fontSize: 'clamp(2.2rem, 11vw, 3.5rem)' }}
          title="Нажми, чтобы скопировать"
        >
          {code.slice(0, 4)}<span className="text-indigo-400/60">·</span>{code.slice(4)}
        </motion.button>
      </AnimatePresence>

      {/* Полоска обратного отсчёта */}
      <div className="mt-4 h-1.5 rounded-full bg-zinc-800 overflow-hidden">
        <motion.div
          className={`h-full rounded-full ${pct > 0.25 ? 'bg-indigo-400' : 'bg-rose-500'}`}
          animate={{ width: `${pct * 100}%` }}
          transition={{ ease: 'linear', duration: 0.25 }}
        />
      </div>
      <div className="mt-2 flex items-center justify-center gap-3 text-xs">
        {expired ? (
          <span className="text-rose-400">Код истёк</span>
        ) : (
          <span className="text-zinc-400 tabular-nums">действует ещё {mm}:{ss}</span>
        )}
        <motion.button
          whileTap={{ scale: 0.92 }}
          onClick={onRefresh}
          disabled={refreshing}
          className="text-indigo-300 hover:text-indigo-200 disabled:opacity-40 font-medium"
        >
          ↻ {refreshing ? 'обновляем…' : 'новый код'}
        </motion.button>
      </div>
    </div>
  )
}

function DeviceRow({ device, onRevoke }) {
  return (
    <motion.li
      layout
      initial={{ opacity: 0, x: -16 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 16, height: 0, marginBottom: 0 }}
      transition={{ type: 'spring', stiffness: 400, damping: 30 }}
      className="flex items-center gap-3 bg-zinc-800/60 border border-zinc-800 rounded-xl px-3 py-2.5"
    >
      <span className="text-xl shrink-0">⌚</span>
      <div className="min-w-0 flex-1">
        <div className="text-white text-sm font-medium truncate">{device.name}</div>
        <div className="text-zinc-500 text-[11px]">{relTime(device.last_seen_at)}</div>
      </div>
      <motion.button
        whileTap={{ scale: 0.9 }}
        onClick={() => onRevoke(device)}
        className="text-red-400 hover:text-red-300 text-base px-1 shrink-0"
        title="Отвязать"
      >
        🗑
      </motion.button>
    </motion.li>
  )
}

export default function WatchPairSheet({ open, onClose }) {
  const toast = useToast()
  const { confirm, element: confirmEl } = useConfirmDialog()
  const [code, setCode] = useState(null)
  const [ttl, setTtl] = useState(300)
  const [refreshing, setRefreshing] = useState(false)
  const [devices, setDevices] = useState(null)
  const [error, setError] = useState(null)
  const prevDeviceCount = useRef(0)

  const fetchCode = useCallback(async () => {
    setRefreshing(true)
    try {
      const d = await watchApi.startPairing()
      setCode(d.code)
      setTtl(d.expires_in || 300)
      setError(null)
    } catch (e) {
      setError(e.message || 'Не вышло получить код')
      toast.error('Не вышло получить код привязки')
    } finally {
      setRefreshing(false)
    }
  }, [toast])

  const fetchDevices = useCallback(async (announce) => {
    try {
      const d = await watchApi.listDevices()
      const list = d.devices || []
      if (announce && list.length > prevDeviceCount.current && prevDeviceCount.current >= 0) {
        toast.success('⌚ Часы привязаны!')
        confetti({ particleCount: 80, spread: 70, origin: { y: 0.3 }, disableForReducedMotion: true })
        // код израсходован — сразу готовим следующий
        fetchCode()
      }
      prevDeviceCount.current = list.length
      setDevices(list)
    } catch {
      setDevices((d) => (d === null ? [] : d))
    }
  }, [toast, fetchCode])

  // Инициализация при открытии
  useEffect(() => {
    if (!open) return
    setCode(null)
    setDevices(null)
    prevDeviceCount.current = -1   // первый fetch только засеивает счётчик
    fetchCode()
    fetchDevices(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  // Поллинг устройств, пока шторка открыта — ловим момент привязки
  useEffect(() => {
    if (!open) return
    const id = window.setInterval(() => fetchDevices(true), POLL_MS)
    return () => window.clearInterval(id)
  }, [open, fetchDevices])

  const handleRevoke = async (device) => {
    const ok = await confirm({
      title: `Отвязать «${device.name}»?`,
      description: 'Токен устройства перестанет работать — счёт с него вести будет нельзя.',
      confirmLabel: 'Отвязать',
      destructive: true,
    })
    if (!ok) return
    const prev = devices
    setDevices((ds) => (ds || []).filter((d) => d.id !== device.id))  // оптимистично
    prevDeviceCount.current = Math.max(0, prevDeviceCount.current - 1)
    try {
      await watchApi.revokeDevice(device.id)
      toast.info('Устройство отвязано')
    } catch (e) {
      setDevices(prev)  // откат
      prevDeviceCount.current = (prev || []).length
      toast.error(`Не удалось отвязать: ${e.message || 'ошибка'}`)
    }
  }

  if (!open) return null
  return (
    <AnimatePresence>
      <SheetShell title="⌚ Привязать часы" onClose={onClose}>
        <p className="text-zinc-400 text-sm mb-4">
          Открой приложение на часах, выбери «Привязать» и введи этот код. После
          привязки часы смогут вести счёт сами — без телефона.
        </p>

        {error && !code && (
          <p className="text-red-400 text-sm mb-3">{error}</p>
        )}
        {code === null && !error ? (
          <div className="rounded-2xl bg-zinc-900 border border-zinc-800 px-5 py-8 mb-5 text-center text-zinc-500 text-sm">
            Получаем код…
          </div>
        ) : code !== null && (
          <CodeBlock code={code} ttl={ttl} onRefresh={fetchCode} refreshing={refreshing} />
        )}

        <div className="text-xs uppercase tracking-wider text-zinc-500 mb-2 flex items-center justify-between">
          <span>Привязанные устройства</span>
          {devices?.length > 0 && <span className="text-zinc-600 normal-case">{devices.length}</span>}
        </div>
        {devices === null ? (
          <p className="text-zinc-500 text-sm">Загружаем…</p>
        ) : devices.length === 0 ? (
          <p className="text-zinc-500 text-sm">Пока ничего не привязано.</p>
        ) : (
          <motion.ul layout className="space-y-2">
            <AnimatePresence initial={false}>
              {devices.map((d) => (
                <DeviceRow key={d.id} device={d} onRevoke={handleRevoke} />
              ))}
            </AnimatePresence>
          </motion.ul>
        )}

        {confirmEl}
      </SheetShell>
    </AnimatePresence>
  )
}
