import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { CircleProvider } from "./context/CircleContext.jsx";
import ErrorBoundary from "./ErrorBoundary.jsx";
import ProtectedRoute from "./ProtectedRoute.jsx";
import Login from "./pages/Login.jsx";
import Landing from "./pages/Landing.jsx";
import Closet from "./pages/Closet.jsx";
import Recommendations from "./pages/Recommendations.jsx";
import Feed from "./pages/Feed.jsx";
import Friends from "./pages/Friends.jsx";
import Builder from "./pages/Builder.jsx";
import Circles from "./pages/Circles.jsx";

/* Cross-fades between routes. Keyed on pathname so each page mounts and
   unmounts as its own element; mode="wait" avoids two pages overlapping in the
   scroll flow mid-transition. */
function AnimatedRoutes() {
  const location = useLocation();
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={location.pathname}
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -8 }}
        transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
      >
        <Routes location={location}>
            {/* Public */}
            <Route path="/"      element={<Landing />} />
            <Route path="/login" element={<Login />} />

            {/* Protected — Closet is the home after login */}
            <Route path="/closet"    element={<ProtectedRoute><Closet /></ProtectedRoute>} />
            <Route path="/for-you"   element={<ProtectedRoute><Recommendations /></ProtectedRoute>} />
            <Route path="/outfits"   element={<ProtectedRoute><Builder /></ProtectedRoute>} />
            <Route path="/circles"   element={<ProtectedRoute><Circles /></ProtectedRoute>} />
            <Route path="/feed"      element={<ProtectedRoute><Feed /></ProtectedRoute>} />
            <Route path="/discover"  element={<ProtectedRoute><Friends /></ProtectedRoute>} />

            {/* Redirects */}
            <Route path="/dashboard" element={<Navigate to="/closet" replace />} />
            <Route path="/builder"   element={<Navigate to="/outfits" replace />} />
            <Route path="/recommend" element={<Navigate to="/outfits" replace />} />

            {/* Fallback */}
            <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </motion.div>
    </AnimatePresence>
  );
}

function App() {
  return (
    <ErrorBoundary>
      <CircleProvider>
        <BrowserRouter>
          <AnimatedRoutes />
        </BrowserRouter>
      </CircleProvider>
    </ErrorBoundary>
  );
}

export default App;
