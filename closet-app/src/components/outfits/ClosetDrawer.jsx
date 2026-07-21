import { useState, useMemo, useEffect } from "react";
import "./ClosetDrawer.css";

import { API_BASE as API } from "../../config";

const ZONE_CATS = {
  head:        ["Accessories", "Hats"],
  neck:        ["Accessories", "Jewelry"],
  torso_outer: ["Outerwear", "Jackets"],
  torso_inner: ["Tops", "Shirts", "Innerwear"],
  legs:        ["Bottoms", "Pants", "Skirts"],
  feet:        ["Shoes", "Sneakers"],
  left_acc:    ["Accessories", "Jewelry"],
  right_acc:   ["Accessories", "Bags"],
};

function itemImg(item) {
  if (item.icon_path) return `${API}/icons/${item.icon_path.split(/[/\\]/).pop()}`;
  return `${API}${item.url}`;
}

export default function ClosetDrawer({ items, activeZone, onPickItem, needsZone }) {
  const [search, setSearch]   = useState("");
  const [tab,    setTab]      = useState("suggested");

  // Follow zone changes
  useEffect(() => {
    setTab(activeZone ? "suggested" : "all");
  }, [activeZone]);

  const allCats = useMemo(
    () => [...new Set(items.map((i) => i.category).filter(Boolean))].sort(),
    [items]
  );

  const displayed = useMemo(() => {
    let list = items;
    if (tab === "suggested" && activeZone) {
      const cats = ZONE_CATS[activeZone] ?? [];
      const filtered = list.filter((i) => cats.includes(i.category));
      list = filtered.length > 0 ? filtered : list;
    } else if (tab !== "all" && tab !== "suggested") {
      list = list.filter((i) => i.category === tab);
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter((i) =>
        (i.brand    || "").toLowerCase().includes(q) ||
        (i.type     || "").toLowerCase().includes(q) ||
        (i.color    || "").toLowerCase().includes(q) ||
        (i.category || "").toLowerCase().includes(q)
      );
    }
    return list;
  }, [items, tab, search, activeZone]);

  const zoneName = activeZone
    ? activeZone.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
    : null;

  const tabs = [
    ...(activeZone ? [{ id: "suggested", label: "Suggested" }] : []),
    { id: "all", label: "All" },
    ...allCats.map((c) => ({ id: c, label: c })),
  ];

  return (
    <div className="closet-drawer">
      <div className="cd-header">
        <span className="cd-title">Closet</span>
        {zoneName && <span className="cd-zone-badge">→ {zoneName}</span>}
      </div>

      {needsZone && (
        <div className="cd-needs-zone">
          Select a zone on the canvas first
        </div>
      )}

      <div className="cd-search-wrap">
        <input
          className="cd-search"
          placeholder="Search…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      <div className="cd-tabs">
        {tabs.map((t) => (
          <button
            key={t.id}
            className={`cd-tab${tab === t.id ? " active" : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="cd-grid">
        {displayed.map((item) => (
          <button
            key={item.id}
            className="cd-item"
            onClick={() => onPickItem(item)}
            title={[item.brand, item.color, item.type].filter(Boolean).join(" · ")}
          >
            <img src={itemImg(item)} alt={item.brand || item.filename} className="cd-img" />
            {item.brand && <span className="cd-brand">{item.brand}</span>}
          </button>
        ))}
        {displayed.length === 0 && (
          <p className="cd-empty">
            {search ? `No results for "${search}"` : "Nothing here yet."}
          </p>
        )}
      </div>
    </div>
  );
}
