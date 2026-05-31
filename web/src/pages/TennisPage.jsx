import { useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence } from 'framer-motion'
import { useAuth } from '../context/useAuth'
import TennisScoreboard from '../tennis/TennisScoreboard'
import TennisLobby from '../tennis/TennisLobby'
import { tennisApi } from '../tennis/api'
import {
  ImportSheet,
  NewSessionSheet,
  SessionDetailsSheet,
  StatsSheet,
} from '../tennis/Modals'
import WatchPairSheet from '../watch/WatchPairSheet'

export default function TennisPage() {
  const { userId } = useAuth()
  // view: 'lobby' | 'live'
  const [view, setView] = useState('lobby')
  const [modal, setModal] = useState(null)  // 'new' | 'import' | 'stats' | {type:'session', id}
  const [refreshTick, setRefreshTick] = useState(0)
  const autoRoutedRef = useRef(false)

  // Auto-route один раз на маунт: если есть live-сессия — открываем табло.
  // Дальше всё навигируется явными действиями пользователя.
  useEffect(() => {
    if (autoRoutedRef.current) return
    autoRoutedRef.current = true
    tennisApi.listSessions(20)
      .then((d) => {
        const live = (d.sessions || []).find((s) => !s.ended_at)
        if (live) setView('live')
      })
      .catch(() => {})
  }, [])

  const goToLobby = useCallback(() => {
    setView('lobby')
    setRefreshTick((x) => x + 1)
  }, [])

  const onSessionCreated = useCallback(() => {
    setModal(null)
    setView('live')
  }, [])

  const onImported = useCallback(() => {
    setModal(null)
    setRefreshTick((x) => x + 1)
  }, [])

  const onSessionDeleted = useCallback(() => {
    setModal(null)
    setRefreshTick((x) => x + 1)
  }, [])

  if (view === 'live') {
    return (
      <>
        <TennisScoreboard onBackToLobby={goToLobby} />
      </>
    )
  }

  return (
    <>
      <TennisLobby
        key={refreshTick}
        onStartLive={() => setView('live')}
        onOpenSession={(id) => setModal({ type: 'session', id })}
        onOpenImport={() => setModal('import')}
        onOpenStats={() => setModal('stats')}
        onOpenNewSession={() => setModal('new')}
        onOpenWatch={() => setModal('watch')}
      />
      <AnimatePresence>
        {modal === 'new' && (
          <NewSessionSheet
            open
            onClose={() => setModal(null)}
            onCreated={onSessionCreated}
          />
        )}
        {modal === 'import' && (
          <ImportSheet
            open
            onClose={() => setModal(null)}
            onImported={onImported}
          />
        )}
        {modal === 'stats' && (
          <StatsSheet
            open
            onClose={() => setModal(null)}
          />
        )}
        {modal === 'watch' && (
          <WatchPairSheet
            open
            onClose={() => setModal(null)}
          />
        )}
        {modal?.type === 'session' && (
          <SessionDetailsSheet
            open
            sessionId={modal.id}
            currentUserId={userId}
            onClose={() => setModal(null)}
            onDeleted={onSessionDeleted}
          />
        )}
      </AnimatePresence>
    </>
  )
}
