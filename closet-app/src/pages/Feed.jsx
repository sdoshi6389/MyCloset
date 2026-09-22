import React, { useEffect, useState } from "react";
import axios from "axios";
import Layout from "./Layout";
import { useCircle } from "../context/CircleContext";
import "./Feed.css";

import { API_BASE as API } from "../config";

export default function Feed() {
  const [posts, setPosts] = useState([]);
  const [showCompose, setShowCompose] = useState(false);
  const [caption, setCaption] = useState("");
  const [visibility, setVisibility] = useState("friends");
  const [images, setImages] = useState([]);
  const [imagePreviews, setImagePreviews] = useState([]);
  const [loading, setLoading] = useState(false);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const LIMIT = 20;
  const token = localStorage.getItem("token");
  const currentEmail = localStorage.getItem("userEmail") || "";
  const { activeCircle, setActiveCircle } = useCircle();

  const authH = () => ({ Authorization: `Bearer ${token}` });

  useEffect(() => { fetchFeed(0); }, [activeCircle]);

  // Revoke object URLs when compose modal closes to avoid memory leaks
  useEffect(() => {
    if (!showCompose) {
      imagePreviews.forEach((url) => URL.revokeObjectURL(url));
      setImagePreviews([]);
    }
  }, [showCompose]);

  const fetchFeed = async (newOffset = 0) => {
    try {
      const url = activeCircle
        ? `${API}/circles/${activeCircle.id}/feed`
        : `${API}/feed`;
      const res = await axios.get(url, {
        headers: authH(),
        params: { limit: LIMIT, offset: newOffset },
      });
      const fetched = res.data || [];
      if (newOffset === 0) {
        setPosts(fetched);
      } else {
        setPosts((prev) => [...prev, ...fetched]);
      }
      setOffset(newOffset + LIMIT);
      setHasMore(fetched.length === LIMIT);
    } catch (e) { console.error(e); }
  };

  const handleImageChange = (e) => {
    const files = Array.from(e.target.files);
    setImages(files);
    // Generate preview URLs for selected images
    setImagePreviews(files.map((f) => URL.createObjectURL(f)));
  };

  const createPost = async () => {
    if (!caption.trim() && !images.length) return;
    setLoading(true);
    try {
      const fd = new FormData();
      fd.append("caption", caption.trim());
      fd.append("visibility", visibility);
      images.forEach((f) => fd.append("images", f));
      await axios.post(`${API}/feed`, fd, { headers: authH() });
      setCaption("");
      setImages([]);
      setVisibility("friends");
      setShowCompose(false);
      fetchFeed(0);
    } catch (e) {
      console.error(e);
      alert("Failed to create post.");
    } finally {
      setLoading(false);
    }
  };

  const deletePost = async (postId) => {
    if (!window.confirm("Delete this post?")) return;
    try {
      await axios.delete(`${API}/feed/${postId}`, { headers: authH() });
      setPosts((prev) => prev.filter((p) => p.id !== postId));
    } catch (e) { console.error(e); }
  };

  const toggleLike = async (postId) => {
    try {
      const res = await axios.post(`${API}/feed/${postId}/like`, {}, { headers: authH() });
      setPosts((prev) =>
        prev.map((p) =>
          p.id === postId
            ? { ...p, liked: res.data.liked, like_count: p.like_count + (res.data.liked ? 1 : -1) }
            : p
        )
      );
    } catch (e) { console.error(e); }
  };

  const formatDate = (iso) => {
    if (!iso) return "";
    const d = new Date(iso);
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  };

  return (
    <Layout>
      <div className="feed-header">
        <h1 className="page-heading">{activeCircle ? `${activeCircle.name} — Feed` : "Feed"}</h1>
        <button className="btn-primary" onClick={() => setShowCompose(true)}>+ New Post</button>
      </div>

      {activeCircle && (
        <div className="circle-context-banner">
          <span>Viewing posts from <strong>{activeCircle.name}</strong> members only</span>
          <button onClick={() => setActiveCircle(null)}>Back to Just Me</button>
        </div>
      )}

      {/* ── Compose modal ──────────────────────────────────────────────────── */}
      {showCompose && (
        <div className="modal-overlay" onClick={() => setShowCompose(false)}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()}>
            <h3>Create a Post</h3>

            <div className="field-group">
              <label className="field-label">Caption</label>
              <textarea
                className="field-textarea"
                value={caption}
                onChange={(e) => setCaption(e.target.value)}
                placeholder="What are you wearing today?"
                rows={3}
              />
            </div>

            <div className="field-group">
              <label className="field-label">Visibility</label>
              <select
                className="field-select"
                value={visibility}
                onChange={(e) => setVisibility(e.target.value)}
              >
                <option value="public">🌍 Public</option>
                <option value="friends">👥 Friends only</option>
                <option value="circle">⭕ Circle</option>
                <option value="private">🔒 Private</option>
              </select>
            </div>

            <div className="field-group">
              <label className="field-label">Images (optional)</label>
              <label className="upload-file-label" style={{ display: "inline-block", cursor: "pointer" }}>
                <input
                  type="file"
                  accept="image/*"
                  multiple
                  style={{ display: "none" }}
                  onChange={handleImageChange}
                />
                📁 {images.length ? `${images.length} image(s) selected` : "Choose images"}
              </label>
              {imagePreviews.length > 0 && (
                <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
                  {imagePreviews.map((src, i) => (
                    <img
                      key={i}
                      src={src}
                      alt=""
                      style={{ width: 72, height: 72, objectFit: "cover", borderRadius: 6, border: "1px solid #333" }}
                    />
                  ))}
                </div>
              )}
            </div>

            <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
              <button className="btn-primary" onClick={createPost} disabled={loading}>
                {loading ? "Posting…" : "Post"}
              </button>
              <button className="btn-secondary" onClick={() => setShowCompose(false)}>Cancel</button>
            </div>
          </div>
        </div>
      )}

      {/* ── Posts ─────────────────────────────────────────────────────────── */}
      {posts.length === 0 && (
        <div className="feed-empty">
          <p>Nothing to show yet. Post something or add friends!</p>
        </div>
      )}

      <div className="feed-list">
        {posts.map((post) => (
          <PostCard
            key={post.id}
            post={post}
            currentEmail={currentEmail}
            onLike={() => toggleLike(post.id)}
            onDelete={() => deletePost(post.id)}
            formatDate={formatDate}
          />
        ))}
      </div>

      {hasMore && (
        <div style={{ textAlign: "center", marginTop: 24 }}>
          <button className="btn-secondary" onClick={() => fetchFeed(offset)}>
            Load more
          </button>
        </div>
      )}
    </Layout>
  );
}

function PostCard({ post, currentEmail, onLike, onDelete, formatDate }) {
  const email = post.author_email || post.user_email || null;
  const initial = email ? email[0].toUpperCase() : "?";
  const isOwner = email && currentEmail && email.toLowerCase() === currentEmail.toLowerCase();

  return (
    <div className="post-card">
      {/* Header */}
      <div className="post-header">
        <div className="post-avatar">{initial}</div>
        <div className="post-meta">
          <span className="post-author">{email || "Unknown"}</span>
          <span className="post-date">{formatDate(post.created_at)}</span>
        </div>
        <span className="post-visibility">{VISIBILITY_BADGE[post.visibility] || post.visibility}</span>
        {isOwner && (
          <button
            className="btn-danger"
            style={{ marginLeft: "auto", padding: "4px 8px", fontSize: "0.72rem" }}
            onClick={onDelete}
          >
            Delete
          </button>
        )}
      </div>

      {/* Images */}
      {post.images?.length > 0 && (
        <div className={`post-images count-${Math.min(post.images.length, 3)}`}>
          {post.images.slice(0, 3).map((src, i) => {
            const raw = typeof src === "object" ? (src.url || "") : (src || "");
            const imgUrl = raw.startsWith("http")
              ? raw
              : `${API}/feed/images/${raw.split(/[\\/]/).pop()}`;
            return <img key={i} src={imgUrl} alt="" />;
          })}
        </div>
      )}

      {/* Caption */}
      {post.caption && <p className="post-caption">{post.caption}</p>}

      {/* Actions */}
      <div className="post-actions">
        <button className={`like-btn${post.liked ? " liked" : ""}`} onClick={onLike}>
          {post.liked ? "❤️" : "🤍"} {post.like_count}
        </button>
        {post.outfit_id && (
          <span className="post-outfit-link">✨ Linked outfit #{post.outfit_id}</span>
        )}
      </div>
    </div>
  );
}

const VISIBILITY_BADGE = {
  public:  "🌍",
  friends: "👥",
  circle:  "⭕",
  private: "🔒",
};
