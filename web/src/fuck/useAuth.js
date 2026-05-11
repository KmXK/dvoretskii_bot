import { useCallback, useEffect, useState } from 'react'
import WebApp from '@twa-dev/sdk'
import { api } from './api'

/**
 * Auth lifecycle:
 * 1. Try restoring session via /api/auth/me (cookie).
 * 2. If not authenticated and running inside Telegram WebApp (initData present),
 *    auto-call /api/auth/webapp.
 * 3. Otherwise, expose `loginWithWidget(user)` to be called by the Telegram
 *    Login Widget's onauth callback.
 */
export function useAuth() {
  const [me, setMe] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const refresh = useCallback(async () => {
    const data = await api.me()
    setMe(data.authenticated ? data : null)
    return data
  }, [])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const data = await refresh()
        if (cancelled) return
        if (!data.authenticated && WebApp?.initData) {
          await api.loginWebapp(WebApp.initData)
          if (cancelled) return
          await refresh()
        }
      } catch (e) {
        if (!cancelled) setError(e.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [refresh])

  const loginWithWidget = useCallback(async (user) => {
    setLoading(true)
    setError(null)
    try {
      await api.loginWidget(user)
      await refresh()
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [refresh])

  const logout = useCallback(async () => {
    await api.logout()
    setMe(null)
  }, [])

  return { me, loading, error, loginWithWidget, logout, refresh }
}
