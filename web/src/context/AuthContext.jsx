import { createContext, useCallback, useEffect, useMemo, useState } from 'react'
import WebApp from '@twa-dev/sdk'
import { api } from '../api/client'

export const AuthContext = createContext(null)

function detectMode() {
  const initData = WebApp?.initData
  const platform = WebApp?.platform
  if (initData && platform && platform !== 'unknown') return 'miniapp'
  return 'web'
}

export function AuthProvider({ children }) {
  const [me, setMe] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const mode = useMemo(() => detectMode(), [])

  const refresh = useCallback(async () => {
    const data = await api.get('/api/auth/me')
    setMe(data.authenticated ? data : null)
    return data
  }, [])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        if (mode === 'miniapp' && WebApp?.initData) {
          try {
            await api.post('/api/auth/webapp', { initData: WebApp.initData })
          } catch {
            // fall through to refresh; auth_me will tell us if we're logged in
          }
        }
        if (!cancelled) await refresh()
      } catch (e) {
        if (!cancelled) setError(e.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [refresh, mode])

  const loginWithWidget = useCallback(async (user) => {
    setLoading(true)
    setError(null)
    try {
      await api.post('/api/auth/widget', user)
      await refresh()
    } catch (e) {
      setError(e.message)
      throw e
    } finally {
      setLoading(false)
    }
  }, [refresh])

  const logout = useCallback(async () => {
    await api.post('/api/auth/logout')
    setMe(null)
  }, [])

  const value = useMemo(() => {
    const tgUser = WebApp?.initDataUnsafe?.user
    const userId = me?.user_id ?? tgUser?.id ?? null
    const tgPhoto = tgUser?.photo_url ?? null
    const photoUrl = tgPhoto ?? (userId ? `/api/avatars/${userId}` : null)
    return {
      mode,
      me,
      loading,
      error,
      isAuthenticated: !!me,
      userId,
      username: me?.username ?? tgUser?.username ?? '',
      firstName: me?.first_name ?? tgUser?.first_name ?? '',
      lastName: tgUser?.last_name ?? '',
      photoUrl,
      isAdmin: !!me?.is_admin,
      isPremium: tgUser?.is_premium ?? false,
      initData: WebApp?.initData ?? '',
      webApp: WebApp,
      loginWithWidget,
      logout,
      refresh,
    }
  }, [mode, me, loading, error, loginWithWidget, logout, refresh])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
