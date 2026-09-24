import { useEffect, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useCircle } from "../../context/CircleContext";

const NAV_ITEMS = [
  { to: "/closet",   label: "Closet",  icon: "👗" },
  { to: "/for-you",  label: "For You", icon: "🎯" },
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

  // Collapsed to an icon rail rather than hidden outright, so navigation stays
  // one click away instead of needing the panel back first.
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem("sidebar_collapsed") === "1"
  );
  useEffect(() => {
    localStorage.setItem("sidebar_collapsed", collapsed ? "1" : "0");
  }, [collapsed]);

  const handleLogout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("userEmail");
    setActiveCircle(null);
    navigate("/");
  };

  return (
    <aside className={`sidebar${collapsed ? " sidebar--collapsed" : ""}`}>
      <div className="sidebar-top">
        <div className="sidebar-brand">{collapsed ? "MC" : "MyCloset"}</div>
        <button
          className="sidebar-toggle"
          onClick={() => setCollapsed((c) => !c)}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-expanded={!collapsed}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          <span className="sidebar-toggle-chevron" />
        </button>
      </div>

      {userEmail && (
        <div className="sidebar-user">
          <div className="sidebar-user-avatar" title={userEmail}>{avatarLetter}</div>
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
            {collapsed ? "Me" : "Just Me"}
          </button>
          {circles.map((c) => (
            <button
              key={c.id}
              className={`circle-pill${activeCircle?.id === c.id ? " active" : ""}`}
              onClick={() => setActiveCircle(c)}
              title={c.description || c.name}
            >
              {collapsed ? c.name.slice(0, 2) : c.name}
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
            title={label}
            className={({ isActive }) => `sidebar-link${isActive ? " active" : ""}`}
          >
            <span className="sidebar-icon">{icon}</span>
            <span className="sidebar-link-label">{label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-footer">
        <button className="sidebar-logout" onClick={handleLogout} title="Log out">
          <span className="sidebar-icon">🚪</span>
          <span className="sidebar-link-label">Log out</span>
        </button>
      </div>
    </aside>
  );
}
