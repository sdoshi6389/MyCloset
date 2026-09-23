import { useState, useEffect } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import { motion } from "framer-motion";
import AmbientField from "../components/common/AmbientField";
import "./Login.css";

import { API_BASE as API } from "../config";

export default function Login() {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  // Show "session expired" message if redirected with that flag
  // Handles both React Router state (from ProtectedRoute) and ?expired=1 (from apiClient interceptor)
  useEffect(() => {
    if (location.state?.expired || new URLSearchParams(location.search).get("expired")) {
      setError("Your session expired. Please log in again.");
    }
  }, [location.state, location.search]);

  // Redirect already-logged-in users (only if token is still valid)
  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) return;
    try {
      const payload = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
      if (payload.exp * 1000 > Date.now()) navigate("/closet", { replace: true });
    } catch {
      localStorage.removeItem("token");
    }
  }, [navigate]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch(`${API}/${mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json();

      if (mode === "signup" && res.ok) {
        setMode("login");
        setError("Account created — please log in.");
        setLoading(false);
        return;
      }

      if (data.token) {
        localStorage.setItem("token", data.token);
        localStorage.setItem("userEmail", data.email || "");
        if (data.user_id != null) localStorage.setItem("userId", String(data.user_id));
        navigate("/closet", { replace: true });
      } else {
        setError(data.message || "Something went wrong.");
      }
    } catch {
      setError("Could not reach the server.");
    } finally {
      setLoading(false);
    }
  };

  const EASE = [0.22, 1, 0.36, 1];

  return (
    <div className="login-root">
      <AmbientField variant="hero" />

      <Link to="/" className="login-back">MyCloset</Link>

      <motion.div
        className="login-card"
        initial={{ opacity: 0, y: 22, scale: 0.97 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.55, ease: EASE }}
      >
        <div className="login-brand">
          <h1>{mode === "login" ? "Welcome back" : "Create your closet"}</h1>
          <p>{mode === "login"
            ? "Sign in to pick up where you left off."
            : "Start with one photo and build from there."}</p>
        </div>

        <div className="login-tabs" role="tablist">
          {["login", "signup"].map((m) => (
            <button
              key={m}
              role="tab"
              aria-selected={mode === m}
              className={`login-tab${mode === m ? " active" : ""}`}
              onClick={() => { setMode(m); setError(""); }}
            >
              {mode === m && (
                <motion.span layoutId="login-tab-pill" className="login-tab-pill"
                  transition={{ duration: 0.28, ease: EASE }} />
              )}
              <span className="login-tab-text">{m === "login" ? "Log in" : "Sign up"}</span>
            </button>
          ))}
        </div>

        <form onSubmit={handleSubmit} className="login-form">
          <div className="login-field-group">
            <label className="login-label" htmlFor="login-email">Email</label>
            <input
              id="login-email"
              type="email"
              className="login-input"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
            />
          </div>

          <div className="login-field-group">
            <label className="login-label" htmlFor="login-password">Password</label>
            <input
              id="login-password"
              type="password"
              className="login-input"
              placeholder="Enter your password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete={mode === "login" ? "current-password" : "new-password"}
            />
          </div>

          {error && (
            <motion.p className="login-error" initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
              {error}
            </motion.p>
          )}

          <motion.button
            className="login-submit"
            disabled={loading}
            whileHover={loading ? {} : { y: -2 }}
            whileTap={loading ? {} : { scale: 0.985 }}
            transition={{ duration: 0.18, ease: EASE }}
          >
            {loading ? "Please wait…" : mode === "login" ? "Log in" : "Create account"}
          </motion.button>
        </form>
      </motion.div>
    </div>
  );
}
