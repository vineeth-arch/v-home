/**
 * The photo's own date from JPEG EXIF (DateTimeOriginal, else DateTime), as YYYY-MM-DD. Null when absent or not a JPEG.
 * Read before resizing: the canvas re-encode drops EXIF.
 */
export function exifDate(buf: ArrayBuffer): string | null {
  const v = new DataView(buf)
  if (v.byteLength < 4 || v.getUint16(0) !== 0xffd8) return null
  let off = 2
  while (off + 4 <= v.byteLength) {
    const marker = v.getUint16(off), size = v.getUint16(off + 2)
    if (marker === 0xffe1 && v.getUint32(off + 4) === 0x45786966) return fromTiff(v, off + 10) // "Exif"
    if ((marker & 0xff00) !== 0xff00 || marker === 0xffda) return null // start of image data: no EXIF
    off += 2 + size
  }
  return null
}

function fromTiff(v: DataView, t: number): string | null {
  if (t + 8 > v.byteLength) return null
  const le = v.getUint16(t) === 0x4949
  const u16 = (o: number) => v.getUint16(o, le), u32 = (o: number) => v.getUint32(o, le)
  const entries = (ifd: number) => {
    const out = new Map<number, number>() // tag -> offset of the entry
    if (ifd + 2 > v.byteLength) return out
    const n = u16(ifd)
    for (let i = 0; i < n && ifd + 2 + i * 12 + 12 <= v.byteLength; i++) out.set(u16(ifd + 2 + i * 12), ifd + 2 + i * 12)
    return out
  }
  const ascii = (e: number | undefined) => {
    if (e === undefined) return null
    const len = u32(e + 4), at = len > 4 ? t + u32(e + 8) : e + 8
    if (at + 10 > v.byteLength) return null
    let s = ''; for (let i = 0; i < 10; i++) s += String.fromCharCode(v.getUint8(at + i))
    const m = /^(\d{4}):(\d{2}):(\d{2})$/.exec(s)
    return m && m[1] !== '0000' ? `${m[1]}-${m[2]}-${m[3]}` : null
  }
  const ifd0 = entries(t + u32(t + 4))
  const sub = ifd0.get(0x8769)
  const exif = sub !== undefined ? entries(t + u32(sub + 8)) : new Map<number, number>()
  return ascii(exif.get(0x9003)) ?? ascii(ifd0.get(0x0132))
}
