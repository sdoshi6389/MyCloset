import { NavLink, useNavigate } from "react-router-dom";
import { useCircle } from "../../context/CircleContext";

const NAV_ITEMS = [
  { to: "/closet",   label: "Closet",  icon: "👗" },
  { to: "/outfits",  label: "Outfits", icon: "✨" },
  { to: "/circles",  label: "Circles", icon: "⭕" },
  { to: "/discover", label: "Friends", icon: "👥" },
  { to: "/feed",     label: "Feed",    icon: "📸" },
];

export default function Sidebar() {
  const navigate = useNavigate();
  const { circles, activeCircle, setActiveCircle } = useCircle();
  const userEmail    = localStorage.getItem("userEmail") || "";
  const avatarLetter = userEmail ? userEmail[0].toUpperCase() : "?";

  const handleLogout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("userEmail");
    setActiveCircle(null);
    navigate("/");
  };

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">MyCloset</div>

      {userEmail && (
        <div className="sidebar-user">
          <div className="sidebar-user-avatar">{avatarLetter}</div>
          <span className="sidebar-user-email" title={userEmail}>{userEmail}</span>
        </div>
      )}

      {/* ── Circle switcher ────────────────────────────────────────────────── */}
      <div className="circle-switcher">
        <p className="circle-switcher-label">Viewing as</p>
        <div className="circle-switcher-pills">
          <button
            className={`circle-pill${!activeCircle ? " active" : ""}`}
            onClick={() => setActiveCircle(null)}
            title="Your own closet, outfits, and feed from all friends"
          >
            Just Me
          </button>
          {circles.map((c) => (
            <button
              key={c.id}
              className={`circle-pill${activeCircle?.id === c.id ? " active" : ""}`}
              onClick={() => setActiveCircle(c)}
              title={c.description || c.name}
            >
              {c.name}
            </button>
          ))}
        </div>
      </div>

      {/* ── Nav ─────────────────────────────────────────────────────────────── */}
      <nav className="sidebar-nav">
        {NAV_ITEMS.map(({ to, label, icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) => `sidebar-link${isActive ? " active" : ""}`}
          >
            <span className="sidebar-icon">{icon}</span>
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-footer">
        <button className="sidebar-logout" onClick={handleLogout}>
          <span className="sidebar-icon">🚪</span>
          Log out
        </button>
      </div>
    </aside>
  );
}
