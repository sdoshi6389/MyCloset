/* Shrink a camera photo before it leaves the browser.
 *
 * The server already caps stored photos at 2560px, so this does not change what
 * the app ends up holding -- it only moves the shrink to before the upload
 * instead of after it. That matters because the wire is now the slow part: a
 * 28 MB phone photo takes about 9 s to reach the server on a 25 Mbps uplink,
 * against under 2 s of work once it arrives.
 */
export const MAX_PHOTO_PX = 2560;
/* 0.92 measured within about a decibel of what the server produces, while 0.95
 * and above only grew the file -- on a detailed photo the resampler, not the
 * encoder, is what sets the ceiling. */
const QUALITY = 0.92;

/* Safari is the only browser that decodes HEIC, and a canvas cannot resize what
 * it cannot decode. Those go up untouched and the server converts them. */
const isHeic = (file) =>
  /heic|heif/i.test(file.type || "") || /\.(heic|heif)$/i.test(file.name || "");

/**
 * Returns a smaller JPEG File, or the original when shrinking it would not help
 * or is not possible. Never throws: a failure here costs a slower upload, not a
 * lost photo, because the server handles full-size files either way.
 */
export async function shrinkForUpload(file) {
  if (!file || isHeic(file)) return file;

  let bitmap;
  try {
    bitmap = await createImageBitmap(file);
    const scale = Math.min(1, MAX_PHOTO_PX / Math.max(bitmap.width, bitmap.height));
    // Only re-encode when there are pixels to drop. Re-encoding a photo that is
    // already within the cap would cost a second round of JPEG loss and buy
    // nothing the upload notices.
    if (scale === 1) return file;

    const w = Math.round(bitmap.width * scale);
    const h = Math.round(bitmap.height * scale);
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(bitmap, 0, 0, w, h);

    const blob = await new Promise((res) => canvas.toBlob(res, "image/jpeg", QUALITY));
    if (!blob || blob.size >= file.size) return file;

    const name = (file.name || "photo").replace(/\.[^.]+$/, "") + ".jpg";
    return new File([blob], name, { type: "image/jpeg", lastModified: Date.now() });
  } catch (e) {
    /* Mobile Safari can run out of memory decoding a very large image. */
    console.warn("Client-side shrink failed, sending the original:", e);
    return file;
  } finally {
    bitmap?.close?.();
  }
}
