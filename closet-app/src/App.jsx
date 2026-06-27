import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { CircleProvider } from "./context/CircleContext.jsx";
import ProtectedRoute from "./ProtectedRoute.jsx";
import Login from "./pages/Login.jsx";
import Closet from "./pages/Closet.jsx";
import Feed from "./pages/Feed.jsx";
import Friends from "./pages/Friends.jsx";
import Outfits from "./pages/Outfits.jsx";
import Circles from "./pages/Circles.jsx";

function App() {
  return (
    <CircleProvider>
      <BrowserRouter>
        <Routes>
          {/* Public */}
          <Route path="/" element={<Login />} />

          {/* Protected — Closet is the home after login */}
          <Route path="/closet"   element={<ProtectedRoute><Closet /></ProtectedRoute>} />
          <Route path="/outfits"  element={<ProtectedRoute><Outfits /></ProtectedRoute>} />
          <Route path="/circles"  element={<ProtectedRoute><Circles /></ProtectedRoute>} />
          <Route path="/feed"     element={<ProtectedRoute><Feed /></ProtectedRoute>} />
          <Route path="/discover" element={<ProtectedRoute><Friends /></ProtectedRoute>} />

          {/* Redirects */}
          <Route path="/dashboard" element={<Navigate to="/closet" replace />} />
          <Route path="/builder"   element={<Navigate to="/outfits" replace />} />

          {/* Fallback */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </CircleProvider>
  );
}

export default App;
