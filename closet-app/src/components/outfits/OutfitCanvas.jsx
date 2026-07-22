import { useState, useEffect, useRef } from "react";
import "./OutfitCanvas.css";

import { API_BASE as API, iconSrc, photoSrc } from "../../config";

export const BODY_ZONES = [
  { id: "head",        label: "Hat / Headwear",   hint: "Hat",       yPct:  1, xPct: 50, wPct: 20, hPct: 13, layer: 10 },
  { id: "neck",        label: "Necklace",          hint: "Necklace",  yPct: 13, xPct: 50, wPct: 16, hPct:  6, layer: 11 },
  { id: "torso_outer", label: "Jacket / Coat",     hint: "Outerwear", yPct: 17, xPct: 50, wPct: 90, hPct: 33, layer:  2 },
  { id: "torso_inner", label: "Top / Shirt",       hint: "Top",       yPct: 19, xPct: 50, wPct: 60, hPct: 29, layer:  5 },
  { id: "legs",        label: "Pants / Skirt",     hint: "Bottoms",   yPct: 50, xPct: 50, wPct: 64, hPct: 34, layer:  1 },
  { id: "feet",        label: "Shoes",             hint: "Shoes",     yPct: 83, xPct: 50, wPct: 56, hPct: 14, layer:  0 },
  { id: "left_acc",    label: "Accessory",         hint: "Acc",       yPct: 30, xPct:  7, wPct: 16, hPct: 16, layer:  6, square: true },
  { id: "right_acc",   label: "Bag",               hint: "Bag",       yPct: 30, xPct: 93, wPct: 16, hPct: 16, layer:  6, square: true },
];

export const CAT_TO_ZONE = {
  "Accessories": "head",
  "Hats":        "head",
  "Tops":        "torso_inner",
  "Shirts":      "torso_inner",
  "Outerwear":   "torso_outer",
  "Jackets":     "torso_outer",
  "Bottoms":     "legs",
  "Pants":       "legs",
  "Skirts":      "legs",
  "Shoes":       "feet",
  "Sneakers":    "feet",
  "Innerwear":   "torso_inner",
  "Jewelry":     "neck",
};

function getImgSrc(item) {
  if (!item) return null;
  if (item.icon_path) return iconSrc(item.icon_path);
  return photoSrc(item.url || `/static/${item.user_id ?? ""}/${item.filename}`);
}

function getRawPhotoSrc(item) {
  if (!item) return null;
  return photoSrc(item.url || `/static/${item.user_id ?? ""}/${item.filename}`);
}

export default function OutfitCanvas({
  slots           = {},
  onZoneClick,
  onClearZone,
  activeZone       = null,
  interactive      = false,
  compact          = false,
  pulseEmptyZones  = false,
}) {
  const [hoveredZoneId, setHoveredZoneId] = useState(null);

  const hoveredZone = BODY_ZONES.find((z) => z.id === hoveredZoneId) ?? null;
  const hoveredItem = hoveredZoneId ? (slots[hoveredZoneId] ?? null) : null;

  return (
    <div
      className={[
        "outfit-canvas",
        interactive     ? "oc-interactive"  : "",
        compact         ? "oc-compact"       : "",
        pulseEmptyZones ? "oc-pulse-zones"   : "",
      ].filter(Boolean).join(" ")}
    >
      <div className="oc-aura" />

      {BODY_ZONES.map((zone) => (
        <CanvasZone
          key={zone.id}
          zone={zone}
          item={slots[zone.id] ?? null}
          interactive={interactive}
          isActive={activeZone === zone.id}
          onZoneClick={onZoneClick}
          onClearZone={onClearZone}
          onHoverEnter={() => setHoveredZoneId(zone.id)}
          onHoverLeave={() => setHoveredZoneId(null)}
        />
      ))}

      {/* Photo preview — rendered at canvas level so it's never clipped */}
      {interactive && hoveredItem && hoveredZone && (
        <PhotoPreview item={hoveredItem} zone={hoveredZone} />
      )}
    </div>
  );
}

/** Floating real-photo preview that appears when hovering a filled zone. */
function PhotoPreview({ item, zone }) {
  const src = getRawPhotoSrc(item);
  if (!src) return null;

  // Zones with xPct > 60 are on the right side — show preview on the left, and vice versa.
  const preferLeft = zone.xPct > 60;

  // Vertically center the preview on the zone's midpoint, clamped so it stays in canvas.
  const PREVIEW_H  = 210; // approximate rendered height (px)
  const CANVAS_H   = 720;
  const zoneMidPx  = (zone.yPct / 100) * CANVAS_H + ((zone.hPct ?? zone.wPct) / 100 * CANVAS_H) / 2;
  const topPx      = Math.max(12, Math.min(zoneMidPx - PREVIEW_H / 2, CANVAS_H - PREVIEW_H - 12));

  return (
    <div
      className={`oc-photo-preview ${preferLeft ? "oc-pp-left" : "oc-pp-right"}`}
      style={{ top: topPx }}
    >
      <img src={src} alt={item.brand || "photo"} className="oc-pp-img" />
      {(item.brand || item.type) && (
        <div className="oc-pp-meta">
          {item.brand && <span className="oc-pp-brand">{item.brand}</span>}
          {item.type  && <span className="oc-pp-type">{item.type}</span>}
        </div>
      )}
    </div>
  );
}

function CanvasZone({ zone, item, interactive, isActive, onZoneClick, onClearZone, onHoverEnter, onHoverLeave }) {
  const [entering, setEntering] = useState(false);
  const [exiting,  setExiting]  = useState(false);
  const prevId = useRef(null);
  const isEmpty = !item;
  const isFeet  = zone.id === "feet";

  useEffect(() => {
    if (item && item.id !== prevId.current) {
      prevId.current = item.id;
      setEntering(true);
      const t = setTimeout(() => setEntering(false), 650);
      return () => clearTimeout(t);
    }
    if (!item) prevId.current = null;
  }, [item]);

  const handleRemove = (e) => {
    e.stopPropagation();
    setExiting(true);
    setTimeout(() => { setExiting(false); onClearZone?.(zone.id); }, 300);
  };

  const zStyle = {
    top:   `${zone.yPct}%`,
    left:  `${zone.xPct}%`,
    width: `${zone.wPct}%`,
    ...(zone.square ? { aspectRatio: "1" } : { height: `${zone.hPct}%` }),
    zIndex: isEmpty
      ? (isActive ? 25 : 0)
      : zone.layer + (isActive ? 20 : 0),
  };

  return (
    <div
      className={[
        "oc-zone",
        `oc-z-${zone.id}`,
        isEmpty    ? "oc-empty-zone"  : "oc-filled",
        interactive ? "oc-zone-inter" : "",
        isActive   ? "oc-zone-active" : "",
        entering   ? "oc-entering"    : "",
        exiting    ? "oc-exiting"     : "",
      ].filter(Boolean).join(" ")}
      style={zStyle}
      onClick={interactive && isEmpty ? () => onZoneClick?.(zone.id) : undefined}
      onMouseEnter={!isEmpty && interactive ? onHoverEnter : undefined}
      onMouseLeave={!isEmpty && interactive ? onHoverLeave : undefined}
    >
      {/* ── Filled: show clothing icon ── */}
      {!isEmpty && (
        <>
          {isFeet ? (
            <div className="oc-feet-pair">
              <img src={getImgSrc(item)} alt={item.brand || "shoe"} className="oc-shoe oc-shoe-l" />
              <img src={getImgSrc(item)} alt=""                     className="oc-shoe oc-shoe-r" />
            </div>
          ) : (
            <img src={getImgSrc(item)} alt={item.brand || zone.label} className="oc-item-img" />
          )}
          {interactive && (
            <div className="oc-item-ctrls">
              <button className="oc-ctrl-swap"   onClick={(e) => { e.stopPropagation(); onZoneClick?.(zone.id); }}>↺</button>
              <button className="oc-ctrl-remove" onClick={handleRemove}>✕</button>
            </div>
          )}
        </>
      )}

      {/* ── Empty interactive: hover label ── */}
      {isEmpty && interactive && (
        <span className="oc-zone-label">{zone.hint}</span>
      )}
    </div>
  );
}
