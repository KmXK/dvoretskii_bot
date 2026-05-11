import { createContext, useContext, useMemo } from 'react'
import WebApp from '@twa-dev/sdk'
import { useAuth } from './useAuth'

const TelegramContext = createContext(null)

/**
 * Backwards-compat shim around AuthContext + WebApp SDK. Existing pages call
 * useTelegram() to get userId / username / display info — we now derive userId
 * from the auth session in web mode, falling back to the WebApp SDK in miniapp.
 */
export function TelegramProvider({ children }) {
  const auth = useAuth()
  const value = useMemo(() => {
    const tg = WebApp.initDataUnsafe?.user
    return {
      user: tg ?? null,
      userId: auth.userId,
      firstName: tg?.first_name ?? '',
      lastName: tg?.last_name ?? '',
      username: auth.username || tg?.username || '',
      photoUrl: tg?.photo_url ?? null,
      isPremium: tg?.is_premium ?? false,
      initData: WebApp.initData,
      webApp: WebApp,
      mode: auth.mode,
      isAdmin: auth.isAdmin,
    }
  }, [auth.userId, auth.username, auth.mode, auth.isAdmin])

  return (
    <TelegramContext.Provider value={value}>
      {children}
    </TelegramContext.Provider>
  )
}

export function useTelegram() {
  const ctx = useContext(TelegramContext)
  if (!ctx) throw new Error('useTelegram must be used within TelegramProvider')
  return ctx
}
