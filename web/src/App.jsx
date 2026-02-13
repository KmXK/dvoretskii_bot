import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { AnimatePresence } from 'framer-motion'
import NavBar from './components/NavBar'
import HomePage from './pages/HomePage'
import ChartsPage from './pages/ChartsPage'
import TablePage from './pages/TablePage'
import CasinoPage from './pages/CasinoPage'

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen pb-16 bg-spotify-black">
        <AnimatePresence mode="wait">
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/charts" element={<ChartsPage />} />
            <Route path="/table" element={<TablePage />} />
            <Route path="/casino" element={<CasinoPage />} />
          </Routes>
        </AnimatePresence>
        <NavBar />
      </div>
    </BrowserRouter>
  )
}
