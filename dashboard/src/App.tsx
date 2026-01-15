import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import TracesPage from './pages/TracesPage'
import TraceDetailPage from './pages/TraceDetailPage'
import ComparisonPage from './pages/ComparisonPage'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<TracesPage />} />
          <Route path="traces" element={<TracesPage />} />
          <Route path="traces/:traceId" element={<TraceDetailPage />} />
          <Route path="compare" element={<ComparisonPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
