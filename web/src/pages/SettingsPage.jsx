import { useEffect, useMemo, useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useParams, useNavigate } from 'react-router-dom'
import BackButton from '../components/BackButton'
import { api } from '../api/client'

const NOTIFICATION_TOGGLES = [
  {
    key: 'fr_notifications_enabled',
    title: 'DM по FR',
    desc: 'Бот пишет в личку при смене статуса/приоритета фича-реквеста.',
  },
  {
    key: 'bills_notifications_enabled',
    title: 'DM по Bills',
    desc: 'Напоминания и уведомления от /bills (платежи, предложения).',
  },
]

function NotificationsPanel() {
  const [prefs, setPrefs] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.get('/api/user/me/preferences')
      .then(setPrefs)
      .catch(() => setPrefs({
        fr_notifications_enabled: true,
        bills_notifications_enabled: true,
      }))
  }, [])

  const toggle = async (key) => {
    if (!prefs) return
    setBusy(true)
    try {
      const updated = await api.patch('/api/user/me/preferences', {
        [key]: !prefs[key],
      })
      setPrefs(updated)
    } finally {
      setBusy(false)
    }
  }

  if (!prefs) return null

  return (
    <div className="bg-spotify-dark rounded-xl p-3 mb-4 space-y-3">
      {NOTIFICATION_TOGGLES.map(({ key, title, desc }) => (
        <div key={key} className="flex items-center gap-3">
          <span>{prefs[key] ? '🔔' : '🔕'}</span>
          <div className="flex-1">
            <p className="text-white text-sm font-medium">{title}</p>
            <p className="text-spotify-text/70 text-xs">{desc}</p>
          </div>
          <button
            onClick={() => toggle(key)}
            disabled={busy}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              prefs[key]
                ? 'bg-spotify-green text-black'
                : 'bg-spotify-bg text-spotify-text'
            }`}
          >
            {prefs[key] ? 'Вкл' : 'Выкл'}
          </button>
        </div>
      ))}
    </div>
  )
}

function TabButton({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
        active
          ? 'bg-spotify-green text-black'
          : 'bg-spotify-dark text-spotify-text hover:text-white'
      }`}
    >
      {children}
    </button>
  )
}

function ChatPicker({ chats, currentId, onChange }) {
  if (chats.length === 0) return null
  return (
    <select
      value={currentId ?? ''}
      onChange={e => onChange(Number(e.target.value))}
      className="w-full bg-spotify-dark text-white rounded-lg px-3 py-2 text-sm mb-4"
    >
      {chats.map(c => (
        <option key={c.id} value={c.id}>
          {c.name} {c.is_chat_admin ? '· admin' : ''}
        </option>
      ))}
    </select>
  )
}

function FeaturesTab({ chatId, data, canEdit, refresh }) {
  const [busy, setBusy] = useState(false)
  const [openCap, setOpenCap] = useState(null)
  const enabled = useMemo(() => new Set(data.enabled_capabilities), [data])
  const disabled = useMemo(() => new Set(data.disabled_features), [data])
  const caps = data.capabilities

  const persist = async (next) => {
    setBusy(true)
    try {
      await api.patch(`/api/chats/${chatId}/settings`, next)
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  const toggleCap = (cap) => {
    if (!canEdit) return
    const e = new Set(enabled)
    const d = new Set(disabled)
    if (e.has(cap)) {
      e.delete(cap)
      for (const f of caps[cap].features) d.delete(f.slug)
    } else {
      e.add(cap)
      for (const f of caps[cap].features) d.delete(f.slug)
    }
    persist({
      enabled_capabilities: [...e],
      disabled_features: [...d],
    })
  }

  const toggleFeat = (cap, slug) => {
    if (!canEdit) return
    const e = new Set(enabled)
    const d = new Set(disabled)
    if (!e.has(cap)) e.add(cap)
    if (d.has(slug)) d.delete(slug)
    else d.add(slug)
    persist({
      enabled_capabilities: [...e],
      disabled_features: [...d],
    })
  }

  const capState = (cap) => {
    if (!enabled.has(cap)) return 'off'
    if (caps[cap].features.some(f => disabled.has(f.slug))) return 'partial'
    return 'on'
  }

  return (
    <div className="space-y-2">
      {Object.entries(caps).map(([cap, info]) => {
        const state = capState(cap)
        const icon = state === 'on' ? '✅' : state === 'off' ? '❌' : '➖'
        const isOpen = openCap === cap
        return (
          <div key={cap} className="bg-spotify-dark rounded-xl overflow-hidden">
            <div className="flex items-center">
              <button
                onClick={() => toggleCap(cap)}
                disabled={!canEdit || busy}
                className="flex-1 px-4 py-3 text-left flex items-center gap-2 disabled:opacity-60 hover:bg-white/5"
              >
                <span>{icon}</span>
                <span className="text-white text-sm font-medium">{info.label}</span>
              </button>
              <button
                onClick={() => setOpenCap(isOpen ? null : cap)}
                className="px-3 py-3 text-spotify-text hover:text-white"
              >
                {isOpen ? '▴' : '▾'}
              </button>
            </div>
            <AnimatePresence initial={false}>
              {isOpen && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  className="border-t border-white/5 overflow-hidden"
                >
                  <div className="p-2 space-y-1">
                    {info.features.map(f => {
                      const active = enabled.has(cap) && !disabled.has(f.slug)
                      const label = f.command ? `/${f.command}` : `${f.slug} (passive)`
                      return (
                        <button
                          key={f.slug}
                          onClick={() => toggleFeat(cap, f.slug)}
                          disabled={!canEdit || busy}
                          className="w-full text-left px-3 py-2 text-sm rounded-lg hover:bg-white/5 disabled:opacity-60"
                        >
                          <div className="flex items-center gap-2">
                            <span>{active ? '✅' : '❌'}</span>
                            <span className="text-white font-medium">{label}</span>
                            {f.bundled_with && f.bundled_with.length > 0 && (
                              <span className="text-spotify-text/60 text-xs">
                                + {f.bundled_with.join(', ')}
                              </span>
                            )}
                          </div>
                          {f.description && (
                            <p className="text-spotify-text/70 text-xs mt-0.5 pl-7">
                              {f.description}
                            </p>
                          )}
                        </button>
                      )
                    })}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )
      })}
    </div>
  )
}

function AdminsTab({ chatId, data, canEdit, refresh }) {
  const [adding, setAdding] = useState('')
  const [busy, setBusy] = useState(false)

  const removeAdmin = async (uid) => {
    setBusy(true)
    try {
      await api.delete(`/api/chats/${chatId}/admins/${uid}`)
      await refresh()
    } finally { setBusy(false) }
  }
  const addAdmin = async () => {
    const uid = parseInt(adding, 10)
    if (!uid) return
    setBusy(true)
    try {
      await api.post(`/api/chats/${chatId}/admins`, { user_id: uid })
      setAdding('')
      await refresh()
    } finally { setBusy(false) }
  }

  return (
    <div className="space-y-3">
      <div className="bg-spotify-dark rounded-xl divide-y divide-white/5">
        {data.chat_admins.length === 0 && (
          <div className="px-4 py-3 text-sm text-spotify-text">Чат-админов нет</div>
        )}
        {data.chat_admins.map(uid => (
          <div key={uid} className="flex items-center px-4 py-3">
            <span className="text-white text-sm">id {uid}</span>
            {canEdit && (
              <button
                onClick={() => removeAdmin(uid)}
                disabled={busy}
                className="ml-auto text-xs text-red-400 hover:text-red-300 disabled:opacity-50"
              >
                Снять
              </button>
            )}
          </div>
        ))}
      </div>
      {canEdit && (
        <div className="bg-spotify-dark rounded-xl p-3 flex gap-2">
          <input
            value={adding}
            onChange={e => setAdding(e.target.value)}
            placeholder="user_id"
            className="flex-1 bg-spotify-bg text-white text-sm rounded-lg px-3 py-2"
          />
          <button
            onClick={addAdmin}
            disabled={!adding || busy}
            className="px-3 py-2 bg-spotify-green text-black rounded-lg text-sm font-medium disabled:opacity-50"
          >
            Добавить
          </button>
        </div>
      )}
    </div>
  )
}

function RolesTab() {
  const [roles, setRoles] = useState([])
  const [perms, setPerms] = useState([])
  const [busy, setBusy] = useState(false)
  const [newName, setNewName] = useState('')
  const [openRole, setOpenRole] = useState(null)
  const [adding, setAdding] = useState({})
  const [err, setErr] = useState(null)

  const refresh = useCallback(async () => {
    try {
      const [r, p] = await Promise.all([
        api.get('/api/roles'),
        api.get('/api/permissions'),
      ])
      setRoles(r)
      setPerms(p)
      setErr(null)
    } catch (e) {
      setErr(e.message)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const createRole = async () => {
    if (!newName.trim()) return
    setBusy(true)
    try {
      await api.post('/api/roles', { name: newName.trim() })
      setNewName('')
      await refresh()
    } finally { setBusy(false) }
  }

  const togglePerm = async (role, perm) => {
    const next = new Set(role.permissions)
    if (next.has(perm)) next.delete(perm)
    else next.add(perm)
    await api.patch(`/api/roles/${role.id}`, { permissions: [...next] })
    await refresh()
  }

  const deleteRole = async (id) => {
    if (!confirm('Удалить роль?')) return
    await api.delete(`/api/roles/${id}`)
    await refresh()
  }

  const addUser = async (roleId) => {
    const value = adding[roleId]
    const uid = parseInt(value, 10)
    if (!uid) return
    await api.post(`/api/roles/${roleId}/users`, { user_id: uid })
    setAdding(prev => ({ ...prev, [roleId]: '' }))
    await refresh()
  }

  const removeUser = async (roleId, uid) => {
    await api.delete(`/api/roles/${roleId}/users/${uid}`)
    await refresh()
  }

  if (err) {
    return (
      <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 text-red-400 text-sm">
        {err}
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="bg-spotify-dark rounded-xl p-3 flex gap-2">
        <input
          value={newName}
          onChange={e => setNewName(e.target.value)}
          placeholder="Название новой роли"
          className="flex-1 bg-spotify-bg text-white text-sm rounded-lg px-3 py-2"
        />
        <button
          onClick={createRole}
          disabled={!newName.trim() || busy}
          className="px-3 py-2 bg-spotify-green text-black rounded-lg text-sm font-medium disabled:opacity-50"
        >
          Создать
        </button>
      </div>

      {roles.length === 0 && (
        <p className="text-spotify-text text-sm text-center py-8">Ролей пока нет</p>
      )}

      {roles.map(role => {
        const open = openRole === role.id
        return (
          <div key={role.id} className="bg-spotify-dark rounded-xl overflow-hidden">
            <div className="flex items-center px-4 py-3">
              <button
                onClick={() => setOpenRole(open ? null : role.id)}
                className="flex-1 text-left flex items-center gap-2"
              >
                <span>🎭</span>
                <span className="text-white font-medium">{role.name}</span>
                <span className="text-xs text-spotify-text">
                  {role.user_ids.length} чел · {role.permissions.length} прав
                </span>
              </button>
              <button
                onClick={() => deleteRole(role.id)}
                className="text-xs text-red-400 hover:text-red-300 ml-2"
              >
                🗑
              </button>
            </div>
            <AnimatePresence initial={false}>
              {open && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  className="border-t border-white/5 overflow-hidden"
                >
                  <div className="p-3 space-y-3">
                    <div>
                      <h4 className="text-xs uppercase tracking-wide text-spotify-text mb-2">
                        Permissions
                      </h4>
                      <div className="space-y-1">
                        {perms.map(p => {
                          const has = role.permissions.includes(p.slug)
                          return (
                            <label
                              key={p.slug}
                              className="flex items-center gap-2 text-sm cursor-pointer"
                            >
                              <input
                                type="checkbox"
                                checked={has}
                                onChange={() => togglePerm(role, p.slug)}
                              />
                              <span className="text-white">{p.slug}</span>
                              {p.used_by.length > 0 && (
                                <span className="text-xs text-spotify-text/70">
                                  {p.used_by[0].feature}
                                </span>
                              )}
                            </label>
                          )
                        })}
                      </div>
                    </div>

                    <div>
                      <h4 className="text-xs uppercase tracking-wide text-spotify-text mb-2">
                        Пользователи
                      </h4>
                      <div className="space-y-1">
                        {role.user_ids.map(uid => (
                          <div key={uid} className="flex items-center gap-2 text-sm">
                            <span className="text-white">id {uid}</span>
                            <button
                              onClick={() => removeUser(role.id, uid)}
                              className="ml-auto text-xs text-red-400 hover:text-red-300"
                            >
                              Удалить
                            </button>
                          </div>
                        ))}
                      </div>
                      <div className="flex gap-2 mt-2">
                        <input
                          value={adding[role.id] || ''}
                          onChange={e =>
                            setAdding(prev => ({ ...prev, [role.id]: e.target.value }))
                          }
                          placeholder="user_id"
                          className="flex-1 bg-spotify-bg text-white text-sm rounded-lg px-3 py-2"
                        />
                        <button
                          onClick={() => addUser(role.id)}
                          className="px-3 py-2 bg-spotify-green text-black rounded-lg text-sm font-medium"
                        >
                          +
                        </button>
                      </div>
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )
      })}
    </div>
  )
}

export default function SettingsPage() {
  const { chatId: chatIdParam } = useParams()
  const navigate = useNavigate()
  const [chats, setChats] = useState([])
  const [chatId, setChatId] = useState(chatIdParam ? Number(chatIdParam) : null)
  const [data, setData] = useState(null)
  const [tab, setTab] = useState('features')
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)

  useEffect(() => {
    api.get('/api/settings/chats')
      .then(r => {
        setChats(r.chats || [])
        if (!chatId && r.chats && r.chats.length > 0) {
          setChatId(r.chats[0].id)
        }
        setLoading(false)
      })
      .catch(e => { setErr(e.message); setLoading(false) })
  }, [])

  const refresh = useCallback(async () => {
    if (!chatId) return
    const d = await api.get(`/api/chats/${chatId}/settings`)
    setData(d)
  }, [chatId])

  useEffect(() => {
    if (chatId) {
      navigate(`/settings/${chatId}`, { replace: true })
      setData(null)
      refresh().catch(e => setErr(e.message))
    }
  }, [chatId, refresh, navigate])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-8 h-8 border-2 border-spotify-green border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  if (err) {
    return (
      <div className="px-4 pt-6">
        <BackButton />
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 text-red-400 text-sm">
          {err}
        </div>
      </div>
    )
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="px-4 pt-6 pb-4 max-w-3xl mx-auto"
    >
      <BackButton />
      <h1 className="text-2xl font-bold text-white mb-1">⚙ Настройки</h1>
      <p className="text-spotify-text text-sm mb-4">
        Тонкая настройка бота по чатам
      </p>

      <NotificationsPanel />

      {chats.length > 0 ? (
        <ChatPicker chats={chats} currentId={chatId} onChange={setChatId} />
      ) : (
        <p className="text-spotify-text text-sm py-8 text-center">
          Нет чатов, в которых ты chat-admin или global-admin
        </p>
      )}

      {chatId && data && (
        <>
          <div className="flex gap-2 mb-4 flex-wrap">
            <TabButton active={tab === 'features'} onClick={() => setTab('features')}>
              📦 Функции
            </TabButton>
            <TabButton active={tab === 'admins'} onClick={() => setTab('admins')}>
              👥 Чат-админы
            </TabButton>
            {data.is_global_admin && (
              <TabButton active={tab === 'roles'} onClick={() => setTab('roles')}>
                🎭 Роли
              </TabButton>
            )}
          </div>

          {tab === 'features' && (
            <FeaturesTab
              chatId={chatId}
              data={data}
              canEdit={data.is_chat_admin || data.is_global_admin}
              refresh={refresh}
            />
          )}
          {tab === 'admins' && (
            <AdminsTab
              chatId={chatId}
              data={data}
              canEdit={data.is_chat_admin || data.is_global_admin}
              refresh={refresh}
            />
          )}
          {tab === 'roles' && data.is_global_admin && <RolesTab />}
        </>
      )}
    </motion.div>
  )
}
