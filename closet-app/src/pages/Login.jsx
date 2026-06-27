import { useState, useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import "./Login.css";

const API = "http://localhost:5000";

export default function Login() {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [animStep, setAnimStep] = useState(0);
  const navigate = useNavigate();
  const location = useLocation();

  // Show "session expired" message if redirected with that flag
  useEffect(() => {
    if (location.state?.expired) setError("Your session expired. Please log in again.");
  }, [location.state]);

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

  // Cycle through wardrobe emojis as ambient animation
  const WARDOBE_EMOJIS = ["👗", "👔", "🧥", "👠", "👟", "🧣", "👜", "🕶️"];
  useEffect(() => {
    const t = setInterval(() => setAnimStep((s) => (s + 1) % WARDOBE_EMOJIS.length), 1400);
    return () => clearInterval(t);
  }, []);

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

  return (
    <div className="login-root">
      {/* Ambient floating icons */}
      <div className="login-bg" aria-hidden>
        {WARDOBE_EMOJIS.map((em, i) => (
          <span
            key={i}
            className="login-float-icon"
            style={{
              left: `${10 + i * 11}%`,
              animationDelay: `${i * 0.7}s`,
              opacity: animStep === i ? 1 : 0.18,
            }}
          >
            {em}
          </span>
        ))}
      </div>

      <div className="login-card">
        {/* Brand header */}
        <div className="login-brand">
          <span className="login-brand-icon">{WARDOBE_EMOJIS[animStep]}</span>
          <h1>MyCloset</h1>
          <p>Your personal wardrobe AI</p>
        </div>

        {/* Toggle tabs */}
        <div className="login-tabs">
          <button
            className={`login-tab${mode === "login" ? " active" : ""}`}
            onClick={() => { setMode("login"); setError(""); }}
          >
            Log in
          </button>
          <button
            className={`login-tab${mode === "signup" ? " active" : ""}`}
            onClick={() => { setMode("signup"); setError(""); }}
          >
            Sign up
          </button>
        </div>

        <form onSubmit={handleSubmit} className="login-form">
          <div className="login-field-group">
            <label className="login-label">Email</label>
            <input
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
            <label className="login-label">Password</label>
            <input
              type="password"
              className="login-input"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete={mode === "login" ? "current-password" : "new-password"}
            />
          </div>

          {error && <p className="login-error">{error}</p>}

          <button className="login-submit" disabled={loading}>
            {loading ? "Please wait…" : mode === "login" ? "Log in" : "Create account"}
          </button>
        </form>
      </div>
    </div>
  );
}
