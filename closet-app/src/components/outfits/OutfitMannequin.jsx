import "./OutfitMannequin.css";

import { API_BASE as API } from "../../config";

export const ZONES = [
  { id: "hat",    label: "Hat / Accessories" },
  { id: "outer",  label: "Outerwear"         },
  { id: "top",    label: "Top"               },
  { id: "bottom", label: "Bottom"            },
  { id: "shoes",  label: "Shoes"             },
];

function getImgSrc(item) {
  if (!item) return null;
  if (item.icon_path) return `${API}/icons/${item.icon_path.split(/[/\\]/).pop()}`;
  return `${API}${item.url || `/static/${item.user_id ?? ""}/${item.filename}`}`;
}

export default function OutfitMannequin({
  slots = {},
  onZoneClick,
  onClearZone,
  interactive = false,
  compact = false,
}) {
  const hasAnyItem = ZONES.some((z) => slots[z.id]);

  return (
    <div className={`outfit-mannequin${compact ? " compact" : ""}${interactive ? " interactive" : ""}${hasAnyItem ? " has-items" : ""}`}>
      {ZONES.map((zone) => (
        <OutfitZoneLayer
          key={zone.id}
          zone={zone}
          item={slots[zone.id] ?? null}
          interactive={interactive}
          onZoneClick={onZoneClick}
          onClear={onClearZone}
        />
      ))}

      {/* Empty state call-to-action when canvas is completely empty */}
      {!hasAnyItem && interactive && (
        <div className="mannequin-empty-cta">
          <p>Click a zone below to start building</p>
          <div className="mannequin-cta-zones">
            {ZONES.map((z) => (
              <button key={z.id} className="cta-zone-pill" onClick={() => onZoneClick?.(z.id)}>
                + {z.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function OutfitZoneLayer({ zone, item, interactive, onZoneClick, onClear }) {
  const imgSrc = getImgSrc(item);
  const isEmpty = !item;

  return (
    <div
      className={`outfit-zone outfit-zone-${zone.id}${isEmpty ? " empty" : " filled"}${interactive ? " clickable" : ""}`}
      onClick={interactive && isEmpty ? () => onZoneClick?.(zone.id) : undefined}
      title={isEmpty ? (interactive ? `Add ${zone.label}` : "") : (item.brand || item.filename)}
    >
      {!isEmpty && (
        <>
          <img
            src={imgSrc}
            alt={item.brand || zone.label}
            className="zone-img"
          />
          {interactive && (
            <div className="zone-actions">
              <button
                className="zone-swap"
                onClick={(e) => { e.stopPropagation(); onZoneClick?.(zone.id); }}
              >
                Swap
              </button>
              <button
                className="zone-remove"
                onClick={(e) => { e.stopPropagation(); onClear?.(zone.id); }}
                title="Remove"
              >
                ✕
              </button>
            </div>
          )}
        </>
      )}

      {isEmpty && interactive && (
        <div className="zone-add-hint">
          <span className="zone-add-icon">＋</span>
          <span className="zone-add-label">{zone.label}</span>
        </div>
      )}
    </div>
  );
}
