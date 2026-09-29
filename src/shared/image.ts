/** Longest edge <= max, aspect preserved, never upscaled. */
export function fitWithin(w: number, h: number, max = 1920): { w: number; h: number } {
  if (w <= max && h <= max) return { w, h }
  const s = max / Math.max(w, h)
  return { w: Math.max(1, Math.round(w * s)), h: Math.max(1, Math.round(h * s)) }
}

export class UnsupportedImageError extends Error { constructor() { super('This photo format is not supported.'); this.name = 'UnsupportedImageError' } }

/** Decode (EXIF-rotated), shrink to 1920px, re-encode JPEG 0.82. Throws UnsupportedImageError if the browser cannot decode it. */
export async function resizeToJpeg(file: Blob, max = 1920): Promise<Blob> {
  let bmp: ImageBitmap
  try { bmp = await createImageBitmap(file, { imageOrientation: 'from-image' }) } catch { throw new UnsupportedImageError() }
  const { w, h } = fitWithin(bmp.width, bmp.height, max)
  const c = document.createElement('canvas'); c.width = w; c.height = h
  c.getContext('2d')!.drawImage(bmp, 0, 0, w, h); bmp.close?.()
  const blob = await new Promise<Blob | null>((res) => c.toBlob(res, 'image/jpeg', 0.82))
  if (!blob) throw new UnsupportedImageError()
  return blob
}
