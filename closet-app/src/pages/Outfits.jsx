import React, { useEffect, useState } from "react";
import axios from "axios";
import Layout from "./Layout";
import OutfitCanvas, { BODY_ZONES, CAT_TO_ZONE } from "../components/outfits/OutfitCanvas";
import ClosetDrawer from "../components/outfits/ClosetDrawer";
import { useCircle } from "../context/CircleContext";
import "./Outfits.css";

const API = "http://localhost:5000";

function emptySlots() {
  return Object.fromEntries(BODY_ZONES.map((z) => [z.id, null]));
}

// Backward compatibility: map old DB slot names → new zone IDs
const SLOT_COMPAT = {
  accessories:      "head",
  inner_top:        "torso_inner",
  outer_top:        "torso_outer",
  inner_bottom:     "legs",
  outer_bottom:     "legs",
  inner_left_foot:  "feet",
  outer_left_foot:  "feet",
  inner_right_foot: "feet",
  outer_right_foot: "feet",
  hat:              "head",
  outer:            "torso_outer",
  top:              "torso_inner",
  bottom:           "legs",
  shoes:            "feet",
};

function outfitToSlots(outfit) {
  const m = emptySlots();
  (outfit.items || []).forEach((it) => {
    if (!it.slot) return;
    const key = SLOT_COMPAT[it.slot] ?? it.slot;
    if (key in m && !m[key]) m[key] = it;
  });
  return m;
}

export default function Outfits() {
  const [outfits,      setOutfits]      = useState([]);
  const [closetItems,  setClosetItems]  = useState([]);
  const [slots,        setSlots]        = useState(emptySlots());
  const [outfitName,   setOutfitName]   = useState("");
  const [occasion,     setOccasion]     = useState("");
  const [notes,        setNotes]        = useState("");
  const [building,     setBuilding]     = useState(false);
  const [activeZone,   setActiveZone]   = useState(null);
  const [needsZone,    setNeedsZone]    = useState(false);
  const [ratingMap,    setRatingMap]    = useState({});
  const [recommend,    setRecommend]    = useState([]);

  const token        = localStorage.getItem("token");
  const currentEmail = localStorage.getItem("userEmail") || "";
  const authH        = () => ({ Authorization: `Bearer ${token}` });
  const { activeCircle, setActiveCircle } = useCircle();

  useEffect(() => { fetchOutfits(); fetchCloset(); }, [activeCircle]);

  const fetchOutfits = async () => {
    try {
      const url = activeCircle
        ? `${API}/circles/${activeCircle.id}/combined-outfits`
        : `${API}/outfits`;
      const r = await axios.get(url, { headers: authH() });
      setOutfits(r.data);
    } catch (e) { console.error(e); }
  };

  const fetchCloset = async () => {
    try {
      const r = await axios.get(`${API}/get_closet_images`, { headers: authH() });
      setClosetItems(r.data);
    } catch (e) { console.error(e); }
  };

  // ── Item assignment ──────────────────────────────────────────────────────
  const handlePickItem = (item) => {
    const targetZone = activeZone ?? CAT_TO_ZONE[item.category] ?? null;
    if (!targetZone) {
      setNeedsZone(true);
      setTimeout(() => setNeedsZone(false), 2200);
      return;
    }
    setSlots((prev) => ({ ...prev, [targetZone]: item }));
    setActiveZone(null);
    setNeedsZone(false);
  };

  const handleZoneClick = (zoneId) => {
    setActiveZone((prev) => (prev === zoneId ? null : zoneId));
    setNeedsZone(false);
  };

  const clearSlot = (zoneId) => {
    setSlots((prev) => ({ ...prev, [zoneId]: null }));
    if (activeZone === zoneId) setActiveZone(null);
  };

  const cancelBuilder = () => {
    setBuilding(false);
    setSlots(emptySlots());
    setActiveZone(null);
    setNeedsZone(false);
  };

  const saveOutfit = async () => {
    const name = outfitName.trim() || "My Outfit";
    const slotsPayload = Object.fromEntries(
      Object.entries(slots).filter(([, v]) => v !== null).map(([k, v]) => [k, v.id])
    );
    try {
      await axios.post(
        `${API}/outfits`,
        { name, occasion, notes, slots: slotsPayload },
        { headers: { ...authH(), "Content-Type": "application/json" } }
      );
      cancelBuilder();
      setOutfitName(""); setOccasion(""); setNotes("");
      fetchOutfits();
    } catch (e) { console.error(e); alert("Failed to save outfit."); }
  };

  const deleteOutfit = async (id) => {
    if (!window.confirm("Delete this outfit?")) return;
    try { await axios.delete(`${API}/outfits/${id}`, { headers: authH() }); fetchOutfits(); }
    catch (e) { console.error(e); }
  };

  const rateOutfit = async (outfitId, rating) => {
    try {
      await axios.post(
        `${API}/outfits/${outfitId}/rate`,
        { rating },
        { headers: { ...authH(), "Content-Type": "application/json" } }
      );
      setRatingMap((prev) => ({ ...prev, [outfitId]: rating }));
    } catch (e) { console.error(e); }
  };

  const getRecommendations = async () => {
    try { const r = await axios.get(`${API}/outfits/recommend`, { headers: authH() }); setRecommend(r.data); }
    catch (e) { console.error(e); }
  };

  const filledCount = BODY_ZONES.filter((z) => slots[z.id]).length;

  // ═══════════════════════════════════════════════════════════════════════════
  // BUILDER WORKSPACE — full-screen three-column layout
  // ═══════════════════════════════════════════════════════════════════════════
  if (building) {
    return (
      <Layout>
        <div className="outfit-workspace">

          {/* ── Left: closet browser ──────────────────────────────── */}
          <ClosetDrawer
            items={closetItems}
            activeZone={activeZone}
            onPickItem={handlePickItem}
            needsZone={needsZone}
          />

          {/* ── Center: deconstructed canvas ──────────────────────── */}
          <div className="workspace-center">
            <OutfitCanvas
              slots={slots}
              onZoneClick={handleZoneClick}
              onClearZone={clearSlot}
              activeZone={activeZone}
              pulseEmptyZones={needsZone}
              interactive
            />
          </div>

          {/* ── Right: controls panel ─────────────────────────────── */}
          <div className="workspace-controls">
            <div className="wc-header">
              <h3 className="wc-title">New Outfit</h3>
              <button className="wc-cancel" onClick={cancelBuilder}>✕</button>
            </div>

            {/* Composition summary */}
            <div className="wc-composition">
              {BODY_ZONES.filter((z) => slots[z.id]).map((zone) => (
                <div key={zone.id} className="wc-row">
                  <span className="wc-zone-label">{zone.label}</span>
                  <span className="wc-item-name">
                    {slots[zone.id].brand || slots[zone.id].filename}
                  </span>
                  <button className="wc-clear" onClick={() => clearSlot(zone.id)}>✕</button>
                </div>
              ))}
              {filledCount === 0 && (
                <p className="wc-empty-msg">
                  Select a zone on the canvas, then click an item from your closet.
                </p>
              )}
            </div>

            {/* Metadata fields */}
            <div className="wc-fields">
              <div className="field-group">
                <label className="field-label">Name</label>
                <input
                  className="field-input"
                  value={outfitName}
                  onChange={(e) => setOutfitName(e.target.value)}
                  placeholder="e.g. Weekend Casual"
                />
              </div>
              <div className="field-group">
                <label className="field-label">Occasion</label>
                <input
                  className="field-input"
                  value={occasion}
                  onChange={(e) => setOccasion(e.target.value)}
                  placeholder="e.g. Work, Date night, Gym"
                />
              </div>
              <div className="field-group">
                <label className="field-label">Notes</label>
                <textarea
                  className="field-textarea"
                  rows={3}
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Style notes…"
                />
              </div>
            </div>

            <button
              className="btn-primary wc-save"
              onClick={saveOutfit}
              disabled={filledCount === 0}
            >
              Save Outfit{filledCount > 0 ? ` (${filledCount})` : ""}
            </button>

            {/* Recommendations */}
            {recommend.length > 0 && (
              <div className="wc-recs">
                <h4 className="wc-recs-title">Recommendations</h4>
                {recommend.map(({ outfit, score, explanation }) => (
                  <div key={outfit.id} className="wc-rec-row">
                    <span className="wc-rec-name">{outfit.name}</span>
                    <span className="wc-rec-why">{explanation}</span>
                  </div>
                ))}
              </div>
            )}

            <button
              className="btn-secondary wc-recommend-btn"
              onClick={getRecommendations}
            >
              Get Recommendations
            </button>
          </div>
        </div>
      </Layout>
    );
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // SAVED OUTFITS VIEW
  // ═══════════════════════════════════════════════════════════════════════════
  return (
    <Layout>
      <div className="outfits-header">
        <h1 className="page-heading">
          {activeCircle ? `${activeCircle.name} — Outfits` : "Outfits"}
        </h1>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn-primary" onClick={() => setBuilding(true)}>+ Build Outfit</button>
          <button className="btn-secondary" onClick={getRecommendations}>Recommend</button>
        </div>
      </div>

      {activeCircle && (
        <div className="circle-context-banner">
          <span>Viewing circle: <strong>{activeCircle.name}</strong> — all members' outfits</span>
          <button onClick={() => setActiveCircle(null)}>Back to Just Me</button>
        </div>
      )}

      {recommend.length > 0 && (
        <div className="section-card" style={{ marginBottom: 24 }}>
          <h3 style={{ color: "#c9b8ff", marginTop: 0 }}>Recommended Outfits</h3>
          {recommend.map(({ outfit, score, explanation }) => (
            <div key={outfit.id} className="recommend-row">
              <span className="recommend-name">{outfit.name}</span>
              <span className="recommend-why">{explanation}</span>
              <span className="recommend-score">Score: {score}</span>
            </div>
          ))}
          <button className="btn-secondary" style={{ marginTop: 8, fontSize: "0.8rem" }} onClick={() => setRecommend([])}>
            Dismiss
          </button>
        </div>
      )}

      {outfits.length === 0 && (
        <div className="closet-empty">No saved outfits yet. Build one above!</div>
      )}

      <div className="outfits-grid">
        {outfits.map((outfit) => {
          const ownedByMe = !outfit.owner_email || outfit.owner_email === currentEmail;
          return (
            <OutfitCard
              key={outfit.id}
              outfit={outfit}
              ownedByMe={ownedByMe}
              rating={ratingMap[outfit.id] || outfit.rating || 0}
              onRate={(n) => rateOutfit(outfit.id, n)}
              onDelete={ownedByMe ? () => deleteOutfit(outfit.id) : null}
            />
          );
        })}
      </div>
    </Layout>
  );
}

function OutfitCard({ outfit, ownedByMe, rating, onRate, onDelete }) {
  return (
    <div className="outfit-card">
      <div className="outfit-card-canvas">
        <OutfitCanvas slots={outfitToSlots(outfit)} compact />
      </div>
      <div className="outfit-card-body">
        <h4 className="outfit-card-name">{outfit.name}</h4>
        {outfit.owner_email && !ownedByMe && (
          <p className="outfit-card-meta" style={{ color: "#7a6aaa", fontSize: "0.75rem" }}>
            by {outfit.owner_email}
          </p>
        )}
        {outfit.occasion && <p className="outfit-card-meta">📅 {outfit.occasion}</p>}
        {outfit.notes    && <p className="outfit-card-meta">{outfit.notes}</p>}
        <div className="outfit-stars">
          {[1, 2, 3, 4, 5].map((n) => (
            <button key={n} className={`star${rating >= n ? " filled" : ""}`} onClick={() => onRate(n)}>★</button>
          ))}
        </div>
        {ownedByMe && onDelete && (
          <button className="btn-danger" style={{ marginTop: 10, width: "100%" }} onClick={onDelete}>
            Delete
          </button>
        )}
      </div>
    </div>
  );
}
