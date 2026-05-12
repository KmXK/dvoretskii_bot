import { lazy, Suspense } from 'react'
import { AnimatePresence } from 'framer-motion'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import { ToastProvider } from './context/ToastContext'
import AuthGate from './layouts/AuthGate'
import AppLayout from './layouts/AppLayout'
import HomePage from './pages/HomePage'

const ArmyPage = lazy(() => import('./pages/ArmyPage'))
const BillsPage = lazy(() => import('./pages/BillsPage'))
const BirthdaysPage = lazy(() => import('./pages/BirthdaysPage'))
const CasinoPage = lazy(() => import('./pages/CasinoPage'))
const PokerPage = lazy(() => import('./pages/PokerPage'))
const BlackjackPage = lazy(() => import('./pages/BlackjackPage'))
const BoardGamesPage = lazy(() => import('./pages/BoardGamesPage'))
const FeaturesPage = lazy(() => import('./pages/FeaturesPage'))
const ProfilePage = lazy(() => import('./pages/ProfilePage'))
const RemindersPage = lazy(() => import('./pages/RemindersPage'))
const StatsPage = lazy(() => import('./pages/StatsPage'))
const ToolsPage = lazy(() => import('./pages/ToolsPage'))
const NotFoundPage = lazy(() => import('./pages/NotFoundPage'))
const TodoPage = lazy(() => import('./pages/TodoPage'))
const FuckAssetsPage = lazy(() => import('./fuck/FuckAssetsPage'))
const FuckCreatePage = lazy(() => import('./fuck/FuckCreatePage'))

function PageFallback() {
  return (
    <div className="min-h-[50vh] flex items-center justify-center">
      <div className="w-8 h-8 border-2 border-spotify-green border-t-transparent rounded-full animate-spin" />
    </div>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <BrowserRouter>
          <AuthGate>
            <AppLayout>
              <AnimatePresence mode="wait">
                <Suspense fallback={<PageFallback />}>
                  <Routes>
                    <Route path="/" element={<HomePage />} />
                    <Route path="/poker" element={<PokerPage />} />
                    <Route path="/blackjack" element={<BlackjackPage />} />
                    <Route path="/boardgames" element={<BoardGamesPage />} />
                    <Route path="/profile" element={<ProfilePage />} />
                    <Route path="/casino" element={<CasinoPage />} />
                    <Route path="/features" element={<FeaturesPage />} />
                    <Route path="/army" element={<ArmyPage />} />
                    <Route path="/todo" element={<TodoPage />} />
                    <Route path="/tools" element={<ToolsPage />} />
                    <Route path="/reminders" element={<RemindersPage />} />
                    <Route path="/birthdays" element={<BirthdaysPage />} />
                    <Route path="/bills" element={<BillsPage />} />
                    <Route path="/stats" element={<StatsPage />} />
                    <Route path="/fuck/assets" element={<FuckAssetsPage />} />
                    <Route path="/fuck/new" element={<FuckCreatePage />} />
                    <Route path="/fuck/assets/:id/edit" element={<FuckCreatePage />} />
                    <Route path="*" element={<NotFoundPage />} />
                  </Routes>
                </Suspense>
              </AnimatePresence>
            </AppLayout>
          </AuthGate>
        </BrowserRouter>
      </ToastProvider>
    </AuthProvider>
  )
}
