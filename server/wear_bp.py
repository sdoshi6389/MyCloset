"""Wear tracking and the weekly outfit log — /wear

  POST   /wear/item/<id>/worn        bump an item's wear count
  POST   /wear/item/<id>/laundry     set or clear the laundry flag
  GET    /wear/week?start=YYYY-MM-DD return the seven days from start
  PUT    /wear/day/<YYYY-MM-DD>      record what was worn that day
  DELETE /wear/day/<YYYY-MM-DD>      clear that day
  GET    /wear/stats?days=7          totals for the wrapped summary

Logging a day is the only thing that moves wear counts: they are derived from
what was actually worn rather than incremented from several places that could
drift apart.
"""
from datetime import date, datetime, timedelta

import jwt
from flask import Blueprint, request, jsonify

from config import JWT_SECRET
from db import get_supa

wear_bp = Blueprint("wear", __name__)


def _get_user_id(req) -> int | None:
    auth = req.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    try:
        return jwt.decode(auth.split(" ")[1], JWT_SECRET, algorithms=["HS256"])["user_id"]
    except Exception:
        return None


def _parse_day(s: str) -> date | None:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _week_start(d: date) -> date:
    """Monday of the week containing d."""
    return d - timedelta(days=d.weekday())


# ── Per-item state ───────────────────────────────────────────────────────────
@wear_bp.route("/item/<int:item_id>/laundry", methods=["POST"])
def set_laundry(item_id: int):
    user_id = _get_user_id(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    flag = bool(data.get("in_laundry", True))
    supa = get_supa()
    try:
        res = (supa.table("closet_items").update({"in_laundry": flag})
               .eq("id", item_id).eq("user_id", user_id).execute())
        if not res.data:
            return jsonify({"message": "Not found"}), 404
        return jsonify({"id": item_id, "in_laundry": flag}), 200
    except Exception as e:
        print(f"❌ /wear/item/{item_id}/laundry: {type(e).__name__}: {e}")
        return jsonify({"message": "Failed"}), 500


@wear_bp.route("/item/<int:item_id>/worn", methods=["POST"])
def mark_worn(item_id: int):
    """Bump a single item, for wearing something outside a logged outfit."""
    user_id = _get_user_id(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401
    supa = get_supa()
    try:
        cur = (supa.table("closet_items").select("wear_count")
               .eq("id", item_id).eq("user_id", user_id).limit(1).execute().data)
        if not cur:
            return jsonify({"message": "Not found"}), 404
        nxt = int(cur[0].get("wear_count") or 0) + 1
        supa.table("closet_items").update({
            "wear_count": nxt, "last_worn": date.today().isoformat(),
        }).eq("id", item_id).eq("user_id", user_id).execute()
        return jsonify({"id": item_id, "wear_count": nxt}), 200
    except Exception as e:
        print(f"❌ /wear/item/{item_id}/worn: {type(e).__name__}: {e}")
        return jsonify({"message": "Failed"}), 500


# ── The week ─────────────────────────────────────────────────────────────────
@wear_bp.route("/week", methods=["GET"])
def get_week():
    user_id = _get_user_id(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    start = _parse_day(request.args.get("start") or "") or _week_start(date.today())
    start = _week_start(start)
    end   = start + timedelta(days=6)
    supa  = get_supa()

    try:
        wears = (supa.table("outfit_wears")
                 .select("id, outfit_id, worn_on, note")
                 .eq("user_id", user_id)
                 .gte("worn_on", start.isoformat())
                 .lte("worn_on", end.isoformat())
                 .execute().data) or []

        by_wear: dict[int, list[dict]] = {}
        item_ids: set[int] = set()
        if wears:
            rows = (supa.table("outfit_wear_items")
                    .select("wear_id, closet_item_id, slot")
                    .in_("wear_id", [w["id"] for w in wears]).execute().data) or []
            for r in rows:
                by_wear.setdefault(r["wear_id"], []).append(r)
                if r.get("closet_item_id"):
                    item_ids.add(r["closet_item_id"])

        meta: dict[int, dict] = {}
        if item_ids:
            rows = (supa.table("closet_items")
                    .select("id, matched_title, caption, type, brand, icon_path, filename, in_laundry")
                    .in_("id", list(item_ids)).execute().data) or []
            meta = {r["id"]: r for r in rows}

        from storage_utils import public_url, thumb_url
        def fmt(row):
            icon = row.get("icon_path")
            fname = icon.replace("\\", "/").split("/")[-1] if icon else None
            return {
                "id":         row["id"],
                "title":      row.get("matched_title") or row.get("caption") or row.get("type"),
                "brand":      row.get("brand"),
                "icon_url":   public_url(f"icons/{fname}") if fname else None,
                "thumb_url":  thumb_url(fname) if fname else None,
                "in_laundry": bool(row.get("in_laundry")),
            }

        by_day = {}
        for w in wears:
            pieces = {}
            for r in by_wear.get(w["id"], []):
                row = meta.get(r.get("closet_item_id"))
                if row and r.get("slot"):
                    pieces[r["slot"]] = fmt(row)
            by_day[w["worn_on"]] = {
                "wear_id": w["id"], "outfit_id": w.get("outfit_id"),
                "note": w.get("note"), "items": pieces,
            }

        days = []
        for i in range(7):
            d = (start + timedelta(days=i)).isoformat()
            days.append({"date": d, **(by_day.get(d) or {"wear_id": None, "items": {}})})

        return jsonify({"start": start.isoformat(), "end": end.isoformat(), "days": days}), 200
    except Exception as e:
        print(f"❌ /wear/week: {type(e).__name__}: {e}")
        return jsonify({"start": start.isoformat(), "days": [], "error": "unavailable"}), 200


@wear_bp.route("/day/<day>", methods=["PUT"])
def set_day(day: str):
    """Body: { outfit_id?, note?, items: { slot: closet_item_id } }

    Wear counts move here and nowhere else, so they stay a function of what was
    logged. Re-logging a day replaces it, and the previous entry's counts are
    rolled back first so editing a day does not inflate totals.
    """
    user_id = _get_user_id(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401
    d = _parse_day(day)
    if not d:
        return jsonify({"message": "Bad date"}), 400

    data  = request.get_json(silent=True) or {}
    items = {str(k): v for k, v in (data.get("items") or {}).items() if v}
    supa  = get_supa()

    try:
        prev = (supa.table("outfit_wears").select("id")
                .eq("user_id", user_id).eq("worn_on", d.isoformat())
                .limit(1).execute().data)

        if prev:
            wear_id = prev[0]["id"]
            old = (supa.table("outfit_wear_items").select("closet_item_id")
                   .eq("wear_id", wear_id).execute().data) or []
            _bump(supa, user_id, [r["closet_item_id"] for r in old if r.get("closet_item_id")], -1)
            supa.table("outfit_wear_items").delete().eq("wear_id", wear_id).execute()
            supa.table("outfit_wears").update({
                "outfit_id": data.get("outfit_id"), "note": data.get("note"),
            }).eq("id", wear_id).execute()
        else:
            created = (supa.table("outfit_wears").insert({
                "user_id": user_id, "worn_on": d.isoformat(),
                "outfit_id": data.get("outfit_id"), "note": data.get("note"),
            }).execute().data)
            wear_id = created[0]["id"]

        if items:
            supa.table("outfit_wear_items").insert([
                {"wear_id": wear_id, "slot": slot, "closet_item_id": int(iid)}
                for slot, iid in items.items()
            ]).execute()
            _bump(supa, user_id, [int(v) for v in items.values()], +1, worn_on=d)

        return jsonify({"wear_id": wear_id, "date": d.isoformat(),
                        "items": len(items)}), 200
    except Exception as e:
        print(f"❌ /wear/day/{day}: {type(e).__name__}: {e}")
        return jsonify({"message": "Failed"}), 500


@wear_bp.route("/day/<day>", methods=["DELETE"])
def clear_day(day: str):
    user_id = _get_user_id(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401
    d = _parse_day(day)
    if not d:
        return jsonify({"message": "Bad date"}), 400
    supa = get_supa()
    try:
        prev = (supa.table("outfit_wears").select("id")
                .eq("user_id", user_id).eq("worn_on", d.isoformat())
                .limit(1).execute().data)
        if not prev:
            return jsonify({"date": d.isoformat(), "cleared": False}), 200
        wear_id = prev[0]["id"]
        old = (supa.table("outfit_wear_items").select("closet_item_id")
               .eq("wear_id", wear_id).execute().data) or []
        _bump(supa, user_id, [r["closet_item_id"] for r in old if r.get("closet_item_id")], -1)
        supa.table("outfit_wears").delete().eq("id", wear_id).execute()
        return jsonify({"date": d.isoformat(), "cleared": True}), 200
    except Exception as e:
        print(f"❌ DELETE /wear/day/{day}: {type(e).__name__}: {e}")
        return jsonify({"message": "Failed"}), 500


def _bump(supa, user_id: int, item_ids: list[int], delta: int, worn_on: date | None = None):
    """Move wear counts by delta, never below zero."""
    ids = [i for i in item_ids if i]
    if not ids:
        return
    rows = (supa.table("closet_items").select("id, wear_count")
            .in_("id", ids).eq("user_id", user_id).execute().data) or []
    for r in rows:
        patch = {"wear_count": max(0, int(r.get("wear_count") or 0) + delta)}
        if delta > 0 and worn_on:
            patch["last_worn"] = worn_on.isoformat()
        supa.table("closet_items").update(patch).eq("id", r["id"]).execute()


# ── Wrapped ──────────────────────────────────────────────────────────────────
@wear_bp.route("/stats", methods=["GET"])
def stats():
    """Totals for the week: days logged, most-worn pieces, what went unworn."""
    user_id = _get_user_id(request)
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401
    start = _parse_day(request.args.get("start") or "") or _week_start(date.today())
    start = _week_start(start)
    end   = start + timedelta(days=6)
    supa  = get_supa()
    try:
        wears = (supa.table("outfit_wears").select("id")
                 .eq("user_id", user_id)
                 .gte("worn_on", start.isoformat())
                 .lte("worn_on", end.isoformat()).execute().data) or []
        counts: dict[int, int] = {}
        if wears:
            rows = (supa.table("outfit_wear_items").select("closet_item_id")
                    .in_("wear_id", [w["id"] for w in wears]).execute().data) or []
            for r in rows:
                iid = r.get("closet_item_id")
                if iid:
                    counts[iid] = counts.get(iid, 0) + 1

        top = []
        if counts:
            ids = sorted(counts, key=counts.get, reverse=True)[:5]
            rows = (supa.table("closet_items")
                    .select("id, matched_title, caption, type, icon_path")
                    .in_("id", ids).execute().data) or []
            from storage_utils import thumb_url
            for r in rows:
                icon = r.get("icon_path")
                fname = icon.replace("\\", "/").split("/")[-1] if icon else None
                top.append({
                    "id": r["id"],
                    "title": r.get("matched_title") or r.get("caption") or r.get("type"),
                    "thumb_url": thumb_url(fname) if fname else None,
                    "times": counts.get(r["id"], 0),
                })
            top.sort(key=lambda x: x["times"], reverse=True)

        total_items = (supa.table("closet_items").select("id", count="exact")
                       .eq("user_id", user_id).limit(1).execute().count) or 0
        in_laundry = (supa.table("closet_items").select("id", count="exact")
                      .eq("user_id", user_id).eq("in_laundry", True)
                      .limit(1).execute().count) or 0

        return jsonify({
            "start": start.isoformat(), "end": end.isoformat(),
            "days_logged": len(wears),
            "pieces_worn": len(counts),
            "closet_size": total_items,
            "in_laundry": in_laundry,
            "top": top,
        }), 200
    except Exception as e:
        print(f"❌ /wear/stats: {type(e).__name__}: {e}")
        return jsonify({"days_logged": 0, "top": [], "error": "unavailable"}), 200
