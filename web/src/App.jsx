import { AnimatePresence } from 'framer-motion'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import AuthGate from './layouts/AuthGate'
import AppLayout from './layouts/AppLayout'
import ArmyPage from './pages/ArmyPage'
import BillsPage from './pages/BillsPage'
import BirthdaysPage from './pages/BirthdaysPage'
import CasinoPage from './pages/CasinoPage'
import PokerPage from './pages/PokerPage'
import BlackjackPage from './pages/BlackjackPage'
import BoardGamesPage from './pages/BoardGamesPage'
import FeaturesPage from './pages/FeaturesPage'
import HomePage from './pages/HomePage'
import ProfilePage from './pages/ProfilePage'
import RemindersPage from './pages/RemindersPage'
import StatsPage from './pages/StatsPage'
import ToolsPage from './pages/ToolsPage'
import NotFoundPage from './pages/NotFoundPage'
import TodoPage from './pages/TodoPage'
import FuckAssetsPage from './fuck/FuckAssetsPage'
import FuckCreatePage from './fuck/FuckCreatePage'

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <AuthGate>
          <AppLayout>
            <AnimatePresence mode="wait">
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
                <Route path="*" element={<NotFoundPage />} />
              </Routes>
            </AnimatePresence>
          </AppLayout>
        </AuthGate>
      </BrowserRouter>
    </AuthProvider>
  )
}
