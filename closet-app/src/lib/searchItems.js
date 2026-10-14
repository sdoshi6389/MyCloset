/* One place that decides whether an item answers to what was typed. Covers the
   words someone actually reaches for -- "black", "nike", "shorts", "henley" --
   rather than the title alone, because a third of these have no brand and the
   garment word often lives in the type rather than the name. */
export function matchesQuery(item, query) {
  const q = (query || "").trim().toLowerCase();
  if (!q) return true;
  const hay = [
    item?.matched_title, item?.caption, item?.title, item?.brand, item?.color,
    item?.type, item?.subcategory, item?.category, item?.size, item?.tag_text,
    Array.isArray(item?.tags) ? item.tags.join(" ") : item?.tags,
  ].filter(Boolean).join(" ").toLowerCase();
  // Every word has to appear somewhere, so "black nike" narrows rather than widens.
  return q.split(/\s+/).every((word) => hay.includes(word));
}
