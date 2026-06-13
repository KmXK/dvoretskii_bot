import { useCallback, useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import * as Dialog from '@radix-ui/react-dialog'
import { Link } from 'react-router-dom'
import { Globe, Users, Plus } from 'lucide-react'
import BackButton from '../components/BackButton'
import Loader from '../components/Loader'
import { fuckApi as api } from './api'
import { useAuth } from '../context/useAuth'

const VIDEO_EXTS = new Set(['mp4', 'webm', 'mov'])
const formatDate = (ts) => ts
  ? new Date(ts * 1000).toLocaleDateString('ru-RU', { day: '2-digit', month: 'short', year: '2-digit' })
  : ''


function ScopeBadge({ scope }) {
  if (scope === 'global') {
    return <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-gold-soft text-gold"><Globe size={12} /> всем</span>
  }
  return <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-blue-500/15 text-blue-300"><Users size={12} /> моим чатам</span>
}


function AssetMedia({ asset }) {
  const isVideo = VIDEO_EXTS.has(asset.extension)
  return (
    <div className="aspect-square bg-black/50 overflow-hidden rounded-t-2xl">
      {isVideo ? (
        <video src={asset.media_url} className="w-full h-full object-contain" muted loop autoPlay playsInline />
      ) : (
        <img src={asset.media_url} alt={asset.name} className="w-full h-full object-contain" loading="lazy" />
      )}
    </div>
  )
}


function ConfirmDeleteDialog({ asset, open, onClose, onConfirmed }) {
  const [busy, setBusy] = useState(false)

  const remove = async () => {
    setBusy(true)
    try {
      await api.deleteAsset(asset.id)
      onConfirmed(asset.id)
      onClose()
    } catch (e) {
      alert('Ошибка: ' + e.message)
      setBusy(false)
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={(v) => { if (!v) onClose() }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/70 z-50 backdrop-blur-sm" />
        <Dialog.Content className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
          bg-spotify-dark rounded-2xl w-[calc(100%-2rem)] max-w-sm z-50 p-6 shadow-2xl">
          <Dialog.Title className="text-white text-lg font-semibold mb-2">Удалить ассет?</Dialog.Title>
          <p className="text-spotify-text text-sm mb-6">
            «{asset?.name}» будет удалён навсегда вместе с файлами.
          </p>
          <div className="flex gap-2">
            <Dialog.Close asChild>
              <button className="flex-1 py-3 rounded-lg text-sm font-medium bg-white/5 text-white hover:bg-white/10">
                Отмена
              </button>
            </Dialog.Close>
            <button
              onClick={remove}
              disabled={busy}
              className="flex-1 py-3 rounded-lg text-sm font-medium bg-red-500 text-white disabled:opacity-40 hover:bg-red-600"
            >
              {busy ? 'Удаляю…' : 'Удалить'}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}


function AssetCard({ asset, onDelete }) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95 }}
      transition={{ duration: 0.2 }}
      className="bg-spotify-dark rounded-2xl overflow-hidden flex flex-col"
    >
      <AssetMedia asset={asset} />
      <div className="p-4 flex flex-col flex-1">
        <div className="flex items-start justify-between gap-3 mb-2">
          <h3 className="text-white text-base font-semibold leading-tight break-all">
            {asset.name}
          </h3>
          <ScopeBadge scope={asset.scope} />
        </div>
        <p className="text-spotify-text text-xs mb-4">
          {asset.owner_username ? `@${asset.owner_username}` : `id:${asset.owner_id}`}
          <span className="mx-1.5 text-spotify-text/40">·</span>
          {formatDate(asset.created_at)}
        </p>

        <div className="mt-auto flex gap-2">
          {asset.can_edit ? (
            <>
              <Link
                to={`/fuck/assets/${asset.id}/edit`}
                className="flex-1 py-2.5 rounded-lg text-sm font-medium text-center bg-white/5 text-white hover:bg-white/10"
              >Изменить</Link>
              <button
                onClick={() => onDelete(asset)}
                className="flex-1 py-2.5 rounded-lg text-sm font-medium bg-red-500/10 text-red-300 hover:bg-red-500/20"
              >Удалить</button>
            </>
          ) : (
            <span className="text-xs text-spotify-text/40 py-2">Только просмотр</span>
          )}
        </div>
      </div>
    </motion.div>
  )
}


export default function FuckAssetsPage() {
  const { me } = useAuth()
  const [assets, setAssets] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [deleting, setDeleting] = useState(null)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      setAssets(await api.listAssets())
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { if (me) reload() }, [me, reload])

  return (
    <div className="bg-spotify-black text-white pb-24">
      <BackButton />
      <div className="max-w-5xl mx-auto px-4 pt-4">
        <header className="flex items-end justify-between gap-4 mb-6">
          <div>
            <h1 className="text-2xl font-bold">/fuck — ассеты</h1>
            <p className="text-spotify-text text-sm mt-1">
              {me.username ? `@${me.username}` : `id:${me.user_id}`}
              {me.is_admin && <span className="ml-2 px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-300 text-xs font-medium">admin</span>}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Link
              to="/fuck/new"
              className="px-4 py-2.5 rounded-lg text-sm font-semibold bg-gold text-black hover:bg-gold-2 transition inline-flex items-center gap-1.5"
            ><Plus size={16} /> Создать</Link>
          </div>
        </header>

        {error && (
          <div className="bg-red-500/15 text-red-300 text-sm rounded-xl px-4 py-3 mb-4">
            {error}
          </div>
        )}

        {loading && assets.length === 0 ? (
          <div className="flex items-center justify-center py-12"><Loader scale={0.6} /></div>
        ) : assets.length === 0 ? (
          <div className="text-center py-16 bg-spotify-dark rounded-2xl">
            <div className="text-6xl mb-4">🤷</div>
            <h3 className="text-white text-lg font-semibold mb-2">Пока пусто</h3>
            <p className="text-spotify-text text-sm mb-6 max-w-xs mx-auto">
              Добавь первую гифку — нажми «Создать» сверху.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            <AnimatePresence>
              {assets.map((a) => (
                <AssetCard
                  key={a.id}
                  asset={a}
                  onDelete={setDeleting}
                />
              ))}
            </AnimatePresence>
          </div>
        )}
      </div>

      <ConfirmDeleteDialog
        asset={deleting}
        open={!!deleting}
        onClose={() => setDeleting(null)}
        onConfirmed={(id) => setAssets((prev) => prev.filter((x) => x.id !== id))}
      />
    </div>
  )
}
