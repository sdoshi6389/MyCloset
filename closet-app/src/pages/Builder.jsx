import React, { useEffect, useState, useCallback } from "react";
import axios from "axios";
import Layout from "./Layout";
import { useCircle } from "../context/CircleContext";
import "./Builder.css";

const API_BASE = "http://localhost:5000";

// ── Zone definitions ──────────────────────────────────────────────────────────
// h    = zone container height when FILLED (px)
// icon = icon image render size when FILLED (px)
// Empty zones return null — they take zero space in the flex layout.
const ZONES = [
  { id: "accessories",       label: "Hat / Accessories", h: 72,  icon: 60  },
  { id: "outer_top",         label: "Jacket / Coat",     h: 160, icon: 148 },
  { id: "inner_top",         label: "Top / Shirt",       h: 132, icon: 118 },
  { id: "inner_bottom",      label: "Pants / Jeans",     h: 140, icon: 126 },
  { id: "outer_bottom",      label: "Skirt / Shorts",    h: 112, icon: 100 },
  { id: "outer_left_foot",   label: "Left Shoe",         h: 92,  icon: 78  },
  { id: "outer_right_foot",  label: "Right Shoe",        h: 92,  icon: 78  },
  { id: "inner_left_foot",   label: "Left Sock",         h: 60,  icon: 48  },
  { id: "inner_right_foot",  label: "Right Sock",        h: 60,  icon: 48  },
];

// Split zones into layout groups
const TORSO_ZONE_IDS = ["accessories", "outer_top", "inner_top", "inner_bottom", "outer_bottom"];
const SHOE_ZONE_IDS  = ["outer_left_foot", "outer_right_foot"];
const SOCK_ZONE_IDS  = ["inner_left_foot", "inner_right_foot"];

const zoneById = Object.fromEntries(ZONES.map((z) => [z.id, z]));

// ── Zone inference ─────────────────────────────────────────────────────────────
// Uses all available text fields from the API response to predict zone.
// Called for closet-panel badges and Smart Fill auto-routing.
function inferZone(item) {
  const text = [item.title, item.type, item.caption, item.category]
    .filter(Boolean).join(" ").toLowerCase();

  if (/\b(jacket|coat|blazer|puffer|windbreaker|anorak|trench|parka|overcoat|outerwear)\b/.test(text)) return "outer_top";
  if (/\b(hoodie|zip.?up|fleece)\b/.test(text) && !/\bshirt\b/.test(text)) return "outer_top";
  if (/\b(shirt|tee|t-shirt|blouse|tank|knit|sweater|pullover|sweatshirt|jersey|camisole|bralette|crop|cardigan)\b/.test(text)) return "inner_top";
  if (/\bhoodi(e|es)\b/.test(text)) return "inner_top";
  if (/\btop\b/.test(text) && !/(jacket|coat|outer)/.test(text)) return "inner_top";
  if (/\b(pants|jeans|trousers|chinos|slacks|legging|jogger|sweatpant|cargo)\b/.test(text)) return "inner_bottom";
  if (/\b(skirt|shorts|mini|midi|maxi|culottes)\b/.test(text)) return "outer_bottom";
  if (/\b(shoe|sneaker|boot|loafer|sandal|heel|flat|pump|oxford|mule|slipper|clog)\b/.test(text)) return "outer_left_foot";
  if (/\b(sock|stocking|tight)\b/.test(text)) return "inner_left_foot";
  if (/\b(hat|cap|beanie|beret|visor|scarf|glasses|sunglasses|bag|purse|belt|watch|jewelry|earring|necklace|bracelet|ring|glove)\b/.test(text)) return "accessories";

  // Fallback on type / category strings
  const t = (item.type || "").toLowerCase();
  const c = (item.category || "").toLowerCase();
  if (t === "outerwear" || c === "outerwear") return "outer_top";
  if (t === "top"       || c === "top")       return "inner_top";
  if (t === "bottom"    || c === "bottom")    return "inner_bottom";
  if (/shoe|footwear/.test(t) || /shoe|footwear/.test(c)) return "outer_left_foot";
  if (/accessory|hat/.test(t) || /accessory|hat/.test(c)) return "accessories";
  if (c === "innerwear") return "inner_top"; // undergarments treated as inner layer

  return null;
}

const ZONE_SHORT = {
  accessories:      "Accessory",
  outer_top:        "Jacket",
  inner_top:        "Top",
  inner_bottom:     "Pants",
  outer_bottom:     "Skirt",
  outer_left_foot:  "Shoes",
  outer_right_foot: "Shoes",
  inner_left_foot:  "Socks",
  inner_right_foot: "Socks",
};

const abs  = (p) => (!p ? null : p.startsWith("http") ? p : `${API_BASE}${p}`);
const tok  = () => localStorage.getItem("token");
const auth = () => ({ Authorization: `Bearer ${tok()}` });

const iconUrl = (icon_path) => {
  if (!icon_path) return null;
  const fname = icon_path.replace(/\\/g, "/").split("/").pop();
  return `${API_BASE}/icons/${fname}`;
};

// ── Builder ───────────────────────────────────────────────────────────────────
export default function Builder() {
  const [items, setItems]     = useState([]);
  const [outfit, setOutfit]   = useState(() =>
    Object.fromEntries(ZONES.map((z) => [z.id, null]))
  );
  const [hovered, setHovered]       = useState(null);
  const [isDragging, setIsDragging] = useState(false);
  const [savedOutfits, setSavedOutfits] = useState([]);

  const [saveModal, setSaveModal] = useState(false);
  const [saveName, setSaveName]   = useState("");
  const [isPrivate, setIsPrivate] = useState(false);
  const [saving, setSaving]       = useState(false);

  const { circles, activeCircle, setActiveCircle } = useCircle();

  // ── Fetch closet items ────────────────────────────────────────────────────
  useEffect(() => {
    const params = activeCircle ? `?circle_id=${activeCircle.id}` : "";
    axios
      .get(`${API_BASE}/builder/get_closet_icons${params}`, { headers: auth() })
      .then((res) => {
        const data = Array.isArray(res.data) ? res.data : [res.data];
        setItems(
          data.filter(Boolean).map((it) => ({
            ...it,
            icon_url:  abs(it.icon_url),
            image_url: abs(it.image_url),
          }))
        );
      })
      .catch(console.error);
  }, [activeCircle]);

  const fetchSaved = useCallback(() => {
    const params = activeCircle ? `?circle_id=${activeCircle.id}` : "";
    axios
      .get(`${API_BASE}/outfits${params}`, { headers: auth() })
      .then((res) => setSavedOutfits(Array.isArray(res.data) ? res.data : []))
      .catch(console.error);
  }, [activeCircle]);

  useEffect(() => { fetchSaved(); }, [fetchSaved]);

  // ── Outfit helpers ────────────────────────────────────────────────────────
  const removeSlot  = (id) => setOutfit((p) => ({ ...p, [id]: null }));
  const resetOutfit = ()   => setOutfit(Object.fromEntries(ZONES.map((z) => [z.id, null])));
  const filledCount = Object.values(outfit).filter(Boolean).length;

  const makeOnDrop = (zoneId) => (e) => {
    e.preventDefault();
    const item = JSON.parse(e.dataTransfer.getData("item"));
    setOutfit((p) => ({ ...p, [zoneId]: item }));
    setIsDragging(false);
  };

  // Smart Fill — auto-route items to inferred zones
  const smartFill = () => {
    const next = { ...outfit };
    for (const item of items.filter((it) => it.is_mine)) {
      const zone = inferZone(item);
      if (!zone) continue;
      if (zone === "outer_left_foot" && !next.outer_left_foot) {
        next.outer_left_foot  = item;
        next.outer_right_foot = next.outer_right_foot || item;
      } else if (zone === "inner_left_foot" && !next.inner_left_foot) {
        next.inner_left_foot  = item;
        next.inner_right_foot = next.inner_right_foot || item;
      } else if (!next[zone]) {
        next[zone] = item;
      }
    }
    setOutfit(next);
  };

  // ── Save flow ─────────────────────────────────────────────────────────────
  const openSave = () => {
    if (!filledCount) return;
    const d = new Date();
    setSaveName(`Outfit – ${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })}`);
    setIsPrivate(false);
    setSaveModal(true);
  };

  const confirmSave = async () => {
    setSaving(true);
    const slots = Object.fromEntries(
      Object.entries(outfit)
        .filter(([, v]) => v)
        .map(([slot, item]) => [slot, item.id])
    );
    try {
      await axios.post(
        `${API_BASE}/outfits`,
        { name: saveName.trim() || "My Outfit", is_private: isPrivate, slots },
        { headers: { ...auth(), "Content-Type": "application/json" } }
      );
      setSaveModal(false);
      fetchSaved();
    } catch (err) {
      alert(err?.response?.data?.message || "Failed to save.");
    } finally {
      setSaving(false);
    }
  };

  const deleteOutfit = async (id) => {
    if (!window.confirm("Delete this outfit?")) return;
    try {
      await axios.delete(`${API_BASE}/outfits/${id}`, { headers: auth() });
      fetchSaved();
    } catch {}
  };

  const loadOutfit = (saved) => {
    const next = Object.fromEntries(ZONES.map((z) => [z.id, null]));
    for (const it of saved.items) {
      if (!(it.slot in next) || !it.icon_path) continue;
      next[it.slot] = {
        id:            it.closet_item_id,
        filename:      it.filename,
        brand:         it.brand,
        icon_url:      iconUrl(it.icon_path),
        image_url:     it.owner_user_id
          ? `${API_BASE}/static/${it.owner_user_id}/${it.filename}`
          : null,
        is_mine:       true,
        owner_initial: null,
      };
    }
    setOutfit(next);
  };

  // ── Hover preview ─────────────────────────────────────────────────────────
  const onEnter = (e, item) => {
    if (!item || isDragging) return;
    const r = e.currentTarget.getBoundingClientRect();
    setHovered({ url: item.image_url, x: r.right + 12, y: r.top });
  };
  const onLeave = () => setHovered(null);

  // ── Grouping ──────────────────────────────────────────────────────────────
  const myItems = items.filter((it) => it.is_mine);
  const byOwner = {};
  for (const it of items.filter((it) => !it.is_mine)) {
    (byOwner[it.owner_email || "Unknown"] = byOwner[it.owner_email || "Unknown"] || []).push(it);
  }

  // Shared zone-drop props builder
  const zoneProps = (zoneId) => ({
    zone:      zoneById[zoneId],
    chosen:    outfit[zoneId],
    isDragging,
    onDrop:    makeOnDrop(zoneId),
    onRemove:  () => removeSlot(zoneId),
    onEnter,
    onLeave,
  });

  const shoesVisible = isDragging || outfit.outer_left_foot || outfit.outer_right_foot;
  const socksVisible = isDragging || outfit.inner_left_foot || outfit.inner_right_foot;

  return (
    <Layout>
      <div className="builder-container">

        {/* LEFT — closet panel */}
        <div className="closet-panel">
          {activeCircle ? (
            <div className="circle-context-banner" style={{ marginBottom: 10 }}>
              <span>Circle: <strong>{activeCircle.name}</strong></span>
              <button onClick={() => setActiveCircle(null)}>Just Me</button>
            </div>
          ) : circles.length > 0 && (
            <div className="circle-switch-row">
              {circles.map((c) => (
                <button key={c.id} className="circle-switch-btn" onClick={() => setActiveCircle(c)}>
                  {c.name}
                </button>
              ))}
            </div>
          )}

          <p className="closet-hint">Drag items → canvas, or use Smart Fill ↗</p>

          {myItems.map((item) => (
            <ClosetItem key={item.id} item={item}
              isDragging={isDragging}
              onDragStart={(e) => { e.dataTransfer.setData("item", JSON.stringify(item)); setIsDragging(true); }}
              onDragEnd={() => setIsDragging(false)}
              onEnter={onEnter} onLeave={onLeave} />
          ))}

          {Object.entries(byOwner).map(([email, ownerItems]) => (
            <div key={email}>
              <div className="owner-section-label">{email}</div>
              {ownerItems.map((item) => (
                <ClosetItem key={item.id} item={item}
                  isDragging={isDragging}
                  onDragStart={(e) => { e.dataTransfer.setData("item", JSON.stringify(item)); setIsDragging(true); }}
                  onDragEnd={() => setIsDragging(false)}
                  onEnter={onEnter} onLeave={onLeave} />
              ))}
            </div>
          ))}
        </div>

        {/* RIGHT — canvas + saved */}
        <div className="slots-panel">

          <div className="slots-header">
            <h2 className="panel-title">Outfit Builder</h2>
            <div className="header-actions">
              {filledCount > 0 && (
                <span className="filled-count">{filledCount} item{filledCount !== 1 ? "s" : ""}</span>
              )}
              <button className="btn-smart" onClick={smartFill}>✦ Smart Fill</button>
              <button className="btn-save" onClick={openSave} disabled={!filledCount}>Save</button>
              <button className="btn-reset" onClick={resetOutfit}>Reset</button>
            </div>
          </div>

          {/* ── Paper-doll canvas ── */}
          <div className="outfit-body-canvas">
            {/* Torso zones: accessories, jacket, top, pants, skirt/shorts */}
            {TORSO_ZONE_IDS.map((id) => (
              <OutfitZone key={id} {...zoneProps(id)} />
            ))}

            {/* Shoes — side-by-side, only rendered when filled or dragging */}
            {shoesVisible && (
              <div className="feet-pair">
                {SHOE_ZONE_IDS.map((id) => (
                  <OutfitZone key={id} {...zoneProps(id)} />
                ))}
              </div>
            )}

            {/* Socks — side-by-side */}
            {socksVisible && (
              <div className="feet-pair">
                {SOCK_ZONE_IDS.map((id) => (
                  <OutfitZone key={id} {...zoneProps(id)} />
                ))}
              </div>
            )}
          </div>

          {/* Saved outfits */}
          {savedOutfits.length > 0 && (
            <div className="saved-section">
              <h3 className="saved-title">
                Saved Outfits
                {activeCircle && <span className="saved-subtitle"> · {activeCircle.name}</span>}
              </h3>
              <div className="saved-scroll">
                {savedOutfits.map((saved) => (
                  <SavedOutfitCard
                    key={saved.id}
                    outfit={saved}
                    onLoad={() => loadOutfit(saved)}
                    onDelete={saved.is_mine ? () => deleteOutfit(saved.id) : null}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Save modal */}
      {saveModal && (
        <div className="modal-backdrop" onClick={() => setSaveModal(false)}>
          <div className="save-modal" onClick={(e) => e.stopPropagation()}>
            <h3 className="modal-title">Save Outfit</h3>
            <input
              className="save-input"
              value={saveName}
              onChange={(e) => setSaveName(e.target.value)}
              placeholder="Outfit name"
              autoFocus
              onKeyDown={(e) => e.key === "Enter" && confirmSave()}
            />
            <label className="privacy-row">
              <input
                type="checkbox"
                checked={!isPrivate}
                onChange={(e) => setIsPrivate(!e.target.checked)}
              />
              <span className="privacy-label">
                {isPrivate ? "Private — only you can see this" : "Shared with circle"}
              </span>
              <span className={`privacy-pill ${isPrivate ? "pill-private" : "pill-shared"}`}>
                {isPrivate ? "Private" : "Circle"}
              </span>
            </label>
            <div className="modal-actions">
              <button className="btn-cancel" onClick={() => setSaveModal(false)}>Cancel</button>
              <button className="btn-confirm" onClick={confirmSave} disabled={saving}>
                {saving ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Hover preview */}
      {hovered?.url && !isDragging && (
        <div className="hover-card" style={{ top: hovered.y, left: hovered.x }}>
          <img src={hovered.url} alt="preview" />
        </div>
      )}
    </Layout>
  );
}

// ── OutfitZone ────────────────────────────────────────────────────────────────
// Key rule: when empty AND not dragging → return null.
// This removes the zone entirely from the flex layout (zero space, no box).
// When dragging: all zones render as visible drop targets.
// When filled: zone renders with the icon floating on the dark canvas.
function OutfitZone({ zone, chosen, isDragging, onDrop, onRemove, onEnter, onLeave }) {
  const [dragOver, setDragOver] = useState(false);

  // Completely remove empty zones when not dragging
  if (!chosen && !isDragging) return null;

  // Prefer transparent icon; fall back to raw photo (lower opacity signals "no icon yet")
  const displayUrl    = chosen ? (chosen.icon_url || chosen.image_url) : null;
  const isPlaceholder = chosen && !chosen.icon_url;

  return (
    <div className="outfit-zone">
      <div
        className={[
          "zone-drop",
          dragOver ? "drag-over" : "",
          chosen    ? "zone-filled" : "",
        ].filter(Boolean).join(" ")}
        style={chosen ? { height: zone.h } : undefined}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { setDragOver(false); onDrop(e); }}
        onMouseEnter={(e) => chosen && onEnter(e, chosen)}
        onMouseLeave={onLeave}
      >
        {displayUrl ? (
          <>
            <img
              src={displayUrl}
              alt=""
              className="zone-icon"
              style={{ width: zone.icon, height: zone.icon, opacity: isPlaceholder ? 0.5 : 1 }}
            />
            {!chosen.is_mine && chosen.owner_initial && (
              <span className="circle-owner-badge zone-badge">{chosen.owner_initial}</span>
            )}
            <button className="zone-remove-btn" onClick={onRemove} title="Remove">×</button>
          </>
        ) : (
          <span className="zone-empty-hint">{zone.label}</span>
        )}
      </div>
    </div>
  );
}

// ── ClosetItem ────────────────────────────────────────────────────────────────
// Shows all items that have any image (icon preferred, photo as fallback).
// Zone badge (Jacket / Top / Pants / etc.) is inferred client-side.
function ClosetItem({ item, isDragging, onDragStart, onDragEnd, onEnter, onLeave }) {
  const displayUrl = item.icon_url || item.image_url;
  if (!displayUrl) return null;

  const zone      = inferZone(item);
  const zoneLabel = zone ? ZONE_SHORT[zone] : null;

  return (
    <div
      className="closet-item"
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onMouseEnter={(e) => onEnter(e, item)}
      onMouseLeave={onLeave}
    >
      <img
        src={displayUrl}
        className="closet-icon"
        alt=""
        style={{ opacity: item.icon_url ? 1 : 0.65 }}
      />
      <div className="item-meta">
        <div className="brand">{item.brand || "—"}</div>
        <div className="title">{item.title || item.caption || ""}</div>
      </div>
      {zoneLabel && <span className="zone-type-badge">{zoneLabel}</span>}
      {!item.is_mine && item.owner_initial && (
        <span className="circle-owner-badge" style={{ marginLeft: 4, flexShrink: 0 }}>
          {item.owner_initial}
        </span>
      )}
    </div>
  );
}

// ── SavedOutfitCard ───────────────────────────────────────────────────────────
function SavedOutfitCard({ outfit, onLoad, onDelete }) {
  const icons = outfit.items
    .filter((it) => it.icon_path)
    .slice(0, 4)
    .map((it) => iconUrl(it.icon_path));

  return (
    <div className="saved-card">
      <div className="saved-icons">
        {icons.length > 0 ? (
          icons.map((url, i) => <img key={i} src={url} alt="" className="saved-icon" />)
        ) : (
          <span className="saved-no-icons">No icons yet</span>
        )}
      </div>
      <div className="saved-name">{outfit.name}</div>
      {!outfit.is_mine && <div className="saved-owner">{outfit.owner_email}</div>}
      <div className="saved-badges">
        {outfit.is_private && <span className="privacy-pill pill-private">Private</span>}
      </div>
      <div className="saved-actions">
        <button className="btn-load" onClick={onLoad}>Load</button>
        {onDelete && <button className="btn-del" onClick={onDelete}>Delete</button>}
      </div>
    </div>
  );
}
