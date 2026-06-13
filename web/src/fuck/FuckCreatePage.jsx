import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { fuckApi as api } from './api'
import { useAuth } from '../context/useAuth'
import Annotator from './annotator/Annotator'

const ACCEPT = 'video/*,image/gif,image/webp'

function AssetForm({
  mode, loaded, busy, error, name, setName, scope, setScope,
  onSave, onCancel, onPickFile, hasLocalFile,
  urlInput, setUrlInput, urlBusy, onFetchUrl,
}) {
  const isEdit = mode === 'edit'
  const fetchDisabled = busy || urlBusy || !urlInput.trim()
  return (
    <div className="bg-spotify-dark rounded-2xl p-4 mb-4">
      <div className="grid grid-cols-1 md:grid-cols-[1fr_auto_auto] gap-3 items-end">
        <label className="block">
          <div className="text-spotify-text text-xs mb-1">Название</div>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={loaded ? 'дай имя ассету' : 'сначала загрузи файл'}
            disabled={!loaded || busy}
            className="w-full bg-black/40 text-white text-base rounded-lg px-3 py-2.5 border border-white/10 focus:border-gold focus:outline-none disabled:opacity-50"
          />
        </label>

        <div>
          <div className="text-spotify-text text-xs mb-1">Доступ</div>
          <div className="flex gap-1.5">
            <button
              onClick={() => setScope('global')}
              disabled={busy}
              className={`px-3 py-2.5 rounded-lg text-sm font-medium transition disabled:opacity-50 ${
                scope === 'global' ? 'bg-gold text-black' : 'bg-white/5 text-white hover:bg-white/10'
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

        <div className="flex gap-2 items-center">
          <button
            onClick={onCancel}
            disabled={busy}
            className="px-4 py-2.5 rounded-lg text-sm bg-white/5 text-white hover:bg-white/10 disabled:opacity-50"
          >Отмена</button>
          <button
            onClick={onSave}
            disabled={!loaded || !name.trim() || busy}
            className="px-5 py-2.5 rounded-lg text-sm font-semibold bg-gold text-black hover:bg-gold-2 disabled:opacity-40 disabled:cursor-not-allowed"
          >{busy ? 'Сохраняю…' : isEdit ? 'Сохранить' : 'Создать'}</button>
        </div>
      </div>

      {!isEdit && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <label className="px-4 py-2.5 rounded-lg text-sm bg-white/5 text-white hover:bg-white/10 cursor-pointer whitespace-nowrap">
            {hasLocalFile ? 'Заменить файл' : 'Файл'}
            <input
              type="file"
              accept={ACCEPT}
              className="hidden"
              disabled={busy || urlBusy}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) onPickFile(f); e.target.value = '' }}
            />
          </label>
          <span className="text-spotify-text/60 text-xs">или</span>
          <div className="flex flex-1 min-w-[200px] gap-1.5">
            <input
              type="url"
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !fetchDisabled) { e.preventDefault(); onFetchUrl() } }}
              placeholder="ссылка на гиф/видео"
              disabled={busy || urlBusy}
              className="flex-1 bg-black/40 text-white text-sm rounded-lg px-3 py-2.5 border border-white/10 focus:border-gold focus:outline-none disabled:opacity-50"
            />
            <button
              onClick={onFetchUrl}
              disabled={fetchDisabled}
              className="px-4 py-2.5 rounded-lg text-sm bg-white/5 text-white hover:bg-white/10 disabled:opacity-40 whitespace-nowrap"
            >{urlBusy ? 'Качаю…' : 'Загрузить'}</button>
          </div>
        </div>
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

  const annotatorRef = useRef(null)
  const loadedAssetRef = useRef(null)
  const initDataRef = useRef(initData)
  const [name, setName] = useState('')
  const [scope, setScope] = useState('global')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [loaded, setLoaded] = useState(false)
  const [hasLocalFile, setHasLocalFile] = useState(false)
  const [urlInput, setUrlInput] = useState('')
  const [urlBusy, setUrlBusy] = useState(false)

  useEffect(() => { initDataRef.current = initData }, [initData])

  useEffect(() => {
    if (mode !== 'edit') return
    if (loadedAssetRef.current === editId) return
    loadedAssetRef.current = editId
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
        const headers = initDataRef.current ? { 'X-Init-Data': initDataRef.current } : {}
        await annotatorRef.current?.loadFromUrl(
          asset.media_url,
          `${asset.id}.${asset.extension}`,
          annotations,
          headers,
        )
        if (!cancelled) setLoaded(true)
      } catch (e) {
        if (!cancelled) {
          loadedAssetRef.current = null
          setError(e.message)
        }
      }
    })()
    return () => { cancelled = true }
  }, [mode, editId])

  const onPickFile = useCallback(async (file) => {
    setError(null)
    try {
      await annotatorRef.current?.loadFromFile(file, null)
      if (!name) setName(file.name.replace(/\.[^.]+$/, ''))
      setLoaded(true)
      setHasLocalFile(true)
    } catch (e) {
      setError(e.message)
      setLoaded(false)
    }
  }, [name])

  const onFetchUrl = useCallback(async () => {
    const url = urlInput.trim()
    if (!url) return
    setError(null)
    setUrlBusy(true)
    try {
      const file = await api.fetchFromUrl(url)
      await onPickFile(file)
      setUrlInput('')
    } catch (e) {
      setError(e.message)
    } finally {
      setUrlBusy(false)
    }
  }, [urlInput, onPickFile])

  const save = async () => {
    setError(null)
    setBusy(true)
    try {
      const res = annotatorRef.current?.getAnnotations()
      if (!res) throw new Error('annotator не готов')
      if (res.error) throw new Error(res.error)
      if (mode === 'edit') {
        await api.patchAsset(editId, {
          name: name.trim(),
          scope,
          annotations: res.data,
        })
      } else {
        await api.createAsset({
          file: res.file,
          annotations: res.data,
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
      <div className="max-w-6xl mx-auto px-4 pt-4">
        <header className="mb-4">
          <h1 className="text-2xl font-bold">
            {mode === 'edit' ? 'Редактировать ассет' : 'Новый ассет'}
          </h1>
          <p className="text-spotify-text text-sm mt-1">
            {mode === 'edit'
              ? 'Двигай bbox\'ы и пересохрани кейфреймы.'
              : 'Загрузи файл, разметь bbox\'ы A и B по кейфреймам, сохрани.'}
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
          onPickFile={onPickFile}
          hasLocalFile={hasLocalFile}
          urlInput={urlInput}
          setUrlInput={setUrlInput}
          urlBusy={urlBusy}
          onFetchUrl={onFetchUrl}
        />

        <div className="bg-spotify-dark rounded-2xl p-3">
          <Annotator ref={annotatorRef} />
        </div>
      </div>
    </div>
  )
}
