import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import BackButton from '../components/BackButton'
import { fuckApi as api } from './api'
import { useAuth } from '../context/useAuth'

const ANNOTATOR_URL = '/fuck/annotator.html?embedded=1'


function AssetForm({ mode, loaded, busy, error, name, setName, scope, setScope, onSave, onCancel }) {
  const isEdit = mode === 'edit'
  return (
    <div className="bg-spotify-dark rounded-2xl p-4 mb-4">
      <div className="grid grid-cols-1 md:grid-cols-[1fr_auto_auto] gap-3 items-end">
        <label className="block">
          <div className="text-spotify-text text-xs mb-1">Название</div>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={loaded ? 'дай имя ассету' : 'сначала загрузи файл в annotator ниже'}
            disabled={!loaded || busy}
            className="w-full bg-black/40 text-white text-base rounded-lg px-3 py-2.5 border border-white/10 focus:border-spotify-green focus:outline-none disabled:opacity-50"
          />
        </label>

        <div>
          <div className="text-spotify-text text-xs mb-1">Доступ</div>
          <div className="flex gap-1.5">
            <button
              onClick={() => setScope('global')}
              disabled={busy}
              className={`px-3 py-2.5 rounded-lg text-sm font-medium transition disabled:opacity-50 ${
                scope === 'global' ? 'bg-spotify-green text-black' : 'bg-white/5 text-white hover:bg-white/10'
              }`}
            >🌍 всем</button>
            <button
              onClick={() => setScope('personal')}
              disabled={busy}
              className={`px-3 py-2.5 rounded-lg text-sm font-medium transition disabled:opacity-50 ${
                scope === 'personal' ? 'bg-blue-500 text-white' : 'bg-white/5 text-white hover:bg-white/10'
              }`}
            >👥 моим</button>
          </div>
        </div>

        <div className="flex gap-2">
          <button
            onClick={onCancel}
            disabled={busy}
            className="px-4 py-2.5 rounded-lg text-sm bg-white/5 text-white hover:bg-white/10 disabled:opacity-50"
          >Отмена</button>
          <button
            onClick={onSave}
            disabled={!loaded || !name.trim() || busy}
            className="px-5 py-2.5 rounded-lg text-sm font-semibold bg-spotify-green text-black hover:bg-spotify-green/90 disabled:opacity-40 disabled:cursor-not-allowed"
          >{busy ? 'Сохраняю…' : isEdit ? 'Сохранить' : 'Создать'}</button>
        </div>
      </div>

      {!loaded && !isEdit && (
        <p className="text-spotify-text/60 text-xs mt-3">
          Загрузи видео/gif/webp в annotator ниже, расставь keyframes для A и B, потом нажми «Создать».
        </p>
      )}
      {error && (
        <div className="mt-3 bg-red-500/15 text-red-300 text-sm rounded-lg px-3 py-2">{error}</div>
      )}
    </div>
  )
}


export default function FuckCreatePage() {
  const navigate = useNavigate()
  const { id: editId } = useParams()
  const { initData } = useAuth()
  const mode = editId ? 'edit' : 'create'

  const iframeRef = useRef(null)
  const pendingResolveRef = useRef(null)
  const editPayloadRef = useRef(null)

  const [loaded, setLoaded] = useState(null)
  const [name, setName] = useState('')
  const [scope, setScope] = useState('global')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    const onMessage = (e) => {
      const msg = e.data
      if (!msg || typeof msg !== 'object') return
      if (msg.type === 'ready' && editPayloadRef.current) {
        iframeRef.current?.contentWindow?.postMessage(
          { type: 'loadFromUrl', ...editPayloadRef.current },
          '*',
        )
      } else if (msg.type === 'loaded') {
        setLoaded(msg)
        if (mode === 'create' && !name) {
          const stem = String(msg.filename || '').replace(/\.[^.]+$/, '')
          setName(stem)
        }
      } else if (msg.type === 'editLoaded') {
        // annotator finished loading existing media + keyframes
      } else if (msg.type === 'annotations') {
        const resolve = pendingResolveRef.current
        pendingResolveRef.current = null
        if (resolve) resolve({ ok: true, ...msg })
      } else if (msg.type === 'error') {
        const resolve = pendingResolveRef.current
        pendingResolveRef.current = null
        if (resolve) resolve({ ok: false, error: msg.error })
        else setError(msg.error)
      }
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [name, mode])

  useEffect(() => {
    if (mode !== 'edit') return
    let cancelled = false
    ;(async () => {
      try {
        const assets = await api.listAssets()
        const asset = assets.find((a) => a.id === editId)
        if (!asset) throw new Error('ассет не найден или нет доступа')
        if (!asset.can_edit) throw new Error('можно редактировать только свои ассеты')
        const annotations = await api.getAssetData(editId)
        if (cancelled) return
        setName(asset.name)
        setScope(asset.scope)
        editPayloadRef.current = {
          mediaUrl: asset.media_url,
          filename: `${asset.id}.${asset.extension}`,
          annotations,
          initData,
        }
        iframeRef.current?.contentWindow?.postMessage(
          { type: 'loadFromUrl', ...editPayloadRef.current },
          '*',
        )
      } catch (e) {
        if (!cancelled) setError(e.message)
      }
    })()
    return () => { cancelled = true }
  }, [mode, editId, initData])

  const requestAnnotations = useCallback(() => new Promise((resolve) => {
    pendingResolveRef.current = resolve
    iframeRef.current?.contentWindow?.postMessage({ type: 'getAnnotations' }, '*')
    setTimeout(() => {
      if (pendingResolveRef.current === resolve) {
        pendingResolveRef.current = null
        resolve({ ok: false, error: 'annotator не ответил' })
      }
    }, 5000)
  }), [])

  const save = async () => {
    setError(null)
    setBusy(true)
    try {
      const res = await requestAnnotations()
      if (!res.ok) throw new Error(res.error)
      if (mode === 'edit') {
        await api.patchAsset(editId, {
          name: name.trim(),
          scope,
          annotations: res.annotations,
        })
      } else {
        await api.createAsset({
          file: res.file,
          annotations: res.annotations,
          name: name.trim(),
          scope,
        })
      }
      navigate('/fuck/assets')
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="bg-spotify-black text-white pb-24">
      <BackButton />
      <div className="max-w-6xl mx-auto px-4 pt-4">
        <header className="mb-4">
          <h1 className="text-2xl font-bold">
            {mode === 'edit' ? 'Редактировать /fuck-ассет' : 'Новый /fuck-ассет'}
          </h1>
          <p className="text-spotify-text text-sm mt-1">
            {mode === 'edit'
              ? 'Подвинь bbox\'ы и пересохрани кейфреймы.'
              : 'Загрузи видео/gif/webp, разметь bbox\'ы A и B по keyframes и нажми «Создать».'}
          </p>
        </header>

        <AssetForm
          mode={mode}
          loaded={loaded}
          busy={busy}
          error={error}
          name={name}
          setName={setName}
          scope={scope}
          setScope={setScope}
          onSave={save}
          onCancel={() => navigate('/fuck/assets')}
        />

        <iframe
          ref={iframeRef}
          src={ANNOTATOR_URL}
          title="annotator"
          className="w-full h-[80vh] rounded-2xl border-0 bg-black"
        />
      </div>
    </div>
  )
}
