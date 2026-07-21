import { useState, useMemo } from "react";
import "./ItemPickerPanel.css";

import { API_BASE as API } from "../../config";

// Which categories are most relevant per zone (shown as default tab)
const ZONE_DEFAULT_CAT = {
  hat:    ["Accessories"],
  outer:  ["Outerwear"],
  top:    ["Tops"],
  bottom: ["Bottoms"],
  shoes:  ["Shoes"],
};

function itemImgSrc(item) {
  if (item.icon_path) return `${API}/icons/${item.icon_path.split(/[/\\]/).pop()}`;
  return `${API}${item.url}`;
}

export default function ItemPickerPanel({ zone, zoneName, closetItems, onPick, onClose }) {
  const defaultCats = ZONE_DEFAULT_CAT[zone] ?? [];

  // Build tab list: "Suggested" (zone-relevant) + "All" + any other categories present
  const allCats = useMemo(() => {
    const cats = new Set(closetItems.map((i) => i.category).filter(Boolean));
    return Array.from(cats).sort();
  }, [closetItems]);

  const [activeTab, setActiveTab] = useState("suggested");
  const [search, setSearch] = useState("");

  const displayed = useMemo(() => {
    let list = closetItems;
    if (activeTab === "suggested") {
      list = list.filter((i) => defaultCats.includes(i.category));
      // If nothing matches, fall back to all
      if (list.length === 0) list = closetItems;
    } else if (activeTab !== "all") {
      list = list.filter((i) => i.category === activeTab);
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(
        (i) =>
          (i.brand || "").toLowerCase().includes(q) ||
          (i.type  || "").toLowerCase().includes(q) ||
          (i.color || "").toLowerCase().includes(q) ||
          (i.filename || "").toLowerCase().includes(q)
      );
    }
    return list;
  }, [closetItems, activeTab, search, defaultCats]);

  const tabs = [
    { id: "suggested", label: `For ${zoneName}` },
    { id: "all",       label: "All Items"       },
    ...allCats.map((c) => ({ id: c, label: c })),
  ];

  return (
    <div className="item-picker-panel">
      {/* Header */}
      <div className="picker-panel-header">
        <div>
          <p className="picker-panel-zone-label">Adding to</p>
          <h3 className="picker-panel-title">{zoneName}</h3>
        </div>
        <button className="picker-panel-close" onClick={onClose} title="Close">✕</button>
      </div>

      {/* Search */}
      <div className="picker-search-wrap">
        <input
          className="picker-search"
          placeholder="Search brand, color, type…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {/* Category tabs */}
      <div className="picker-tabs">
        {tabs.map((t) => (
          <button
            key={t.id}
            className={`picker-tab${activeTab === t.id ? " active" : ""}`}
            onClick={() => setActiveTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Item grid */}
      <div className="picker-grid">
        {displayed.map((item) => (
          <button
            key={item.id}
            className="picker-item"
            onClick={() => onPick(item)}
            title={item.brand || item.filename}
          >
            <div className="picker-item-img-wrap">
              <img
                src={itemImgSrc(item)}
                alt={item.brand || item.filename}
                className="picker-item-img"
              />
            </div>
            <p className="picker-item-label">{item.brand || item.filename}</p>
            {item.category && <p className="picker-item-cat">{item.category}</p>}
          </button>
        ))}
        {displayed.length === 0 && (
          <p className="picker-empty">
            {search ? `No results for "${search}"` : "Nothing in your closet for this zone yet."}
          </p>
        )}
      </div>
    </div>
  );
}
