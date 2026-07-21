"""
Recommendation impression and user-event logging.

Tables expected in Supabase (create via SQL editor — see bottom of this file):
  - recommendation_logs
  - user_events
"""
import uuid
from datetime import datetime, timezone
from db import get_supa


def log_recommendations(
    user_id: int,
    slot: str,
    outfit_ctx: dict,
    candidates: list[dict],
    context: dict | None = None,
) -> None:
    """
    Write one row per returned candidate to recommendation_logs.
    Called by the engine after the final ranked list is built.
    Non-blocking: exceptions are swallowed so a DB error never kills the API.
    """
    supa = get_supa()
    rows = []
    for rank, item in enumerate(candidates):
        rows.append({
            "recommendation_id": str(uuid.uuid4()),
            "user_id":           user_id,
            "slot":              slot,
            "outfit_ctx":        outfit_ctx,
            "candidate_item_id": str(item.get("id") or item.get("url") or ""),
            "candidate_source":  item.get("source", ""),
            "rank":              rank,
            "final_score":       float(item.get("score", 0)),
            "score_breakdown":   item.get("score_breakdown"),
            "context":           context or {},
            "created_at":        datetime.now(timezone.utc).isoformat(),
        })

    if not rows:
        return
    try:
        supa.table("recommendation_logs").insert(rows).execute()
    except Exception as e:
        print(f"⚠️  recommendation_logs insert failed: {e}")


def log_event(
    user_id: int,
    event_type: str,
    item_id: str | int | None = None,
    outfit_id: int | None = None,
    recommendation_id: str | None = None,
    context: dict | None = None,
) -> None:
    """
    Write a single user-event row.  Valid event_type values:
      recommendation_viewed, recommendation_clicked, recommendation_added,
      recommendation_removed, recommendation_disliked,
      outfit_saved, outfit_posted,
      item_liked, item_skipped.
    """
    supa = get_supa()
    try:
        supa.table("user_events").insert({
            "user_id":           user_id,
            "event_type":        event_type,
            "item_id":           str(item_id) if item_id is not None else None,
            "outfit_id":         outfit_id,
            "recommendation_id": recommendation_id,
            "context":           context or {},
            "created_at":        datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:
        print(f"⚠️  user_events insert failed: {e}")


def mark_recommendation(recommendation_id: str, field: str) -> None:
    """
    Update a was_* boolean on an existing recommendation_logs row.
    field: "was_clicked" | "was_added" | "was_saved" | "was_rejected"
    """
    if field not in ("was_clicked", "was_added", "was_saved", "was_rejected"):
        return
    supa = get_supa()
    try:
        supa.table("recommendation_logs").update({field: True}).eq(
            "recommendation_id", recommendation_id
        ).execute()
    except Exception as e:
        print(f"⚠️  recommendation_logs update ({field}) failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# SQL to run once in the Supabase SQL editor:
# ─────────────────────────────────────────────────────────────────────────────
#
# CREATE TABLE IF NOT EXISTS recommendation_logs (
#     id                 BIGSERIAL PRIMARY KEY,
#     recommendation_id  TEXT NOT NULL,
#     user_id            INTEGER REFERENCES users(id) ON DELETE CASCADE,
#     slot               TEXT,
#     outfit_ctx         JSONB,
#     candidate_item_id  TEXT,
#     candidate_source   TEXT,
#     rank               INTEGER,
#     final_score        FLOAT,
#     score_breakdown    JSONB,
#     context            JSONB,
#     was_clicked        BOOLEAN DEFAULT FALSE,
#     was_added          BOOLEAN DEFAULT FALSE,
#     was_saved          BOOLEAN DEFAULT FALSE,
#     was_rejected       BOOLEAN DEFAULT FALSE,
#     created_at         TIMESTAMPTZ DEFAULT NOW()
# );
#
# CREATE INDEX IF NOT EXISTS idx_rec_logs_user ON recommendation_logs(user_id);
# CREATE INDEX IF NOT EXISTS idx_rec_logs_rec_id ON recommendation_logs(recommendation_id);
#
# CREATE TABLE IF NOT EXISTS user_events (
#     id                 BIGSERIAL PRIMARY KEY,
#     user_id            INTEGER REFERENCES users(id) ON DELETE CASCADE,
#     event_type         TEXT NOT NULL,
#     item_id            TEXT,
#     outfit_id          INTEGER,
#     recommendation_id  TEXT,
#     context            JSONB,
#     created_at         TIMESTAMPTZ DEFAULT NOW()
# );
#
# CREATE INDEX IF NOT EXISTS idx_user_events_user ON user_events(user_id);
# CREATE INDEX IF NOT EXISTS idx_user_events_type ON user_events(event_type);
