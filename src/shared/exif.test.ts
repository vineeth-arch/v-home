import { describe, expect, it } from 'vitest'
import { exifDate } from './exif'

/** Minimal big-endian JPEG: SOI, APP1 Exif with IFD0 -> ExifIFD -> DateTimeOriginal. */
function jpeg(date: string | null, dateTimeOnly = false): ArrayBuffer {
  const tiff: number[] = []
  const w16 = (n: number) => tiff.push((n >> 8) & 255, n & 255)
  const w32 = (n: number) => tiff.push((n >>> 24) & 255, (n >> 16) & 255, (n >> 8) & 255, n & 255)
  const str = `${date ?? '0000:00:00'} 10:20:30\0` // 20 bytes
  tiff.push(0x4d, 0x4d); w16(42); w32(8)
  // IFD0 at 8: one entry
  w16(1)
  if (dateTimeOnly) { w16(0x0132); w16(2); w32(20); w32(26) } else { w16(0x8769); w16(4); w32(1); w32(26) }
  w32(0)
  // at 26: ExifIFD (or the string itself when dateTimeOnly)
  if (dateTimeOnly) for (const ch of str) tiff.push(ch.charCodeAt(0))
  else { w16(1); w16(0x9003); w16(2); w32(20); w32(44); w32(0); for (const ch of str) tiff.push(ch.charCodeAt(0)) }
  const app1 = [0x45, 0x78, 0x69, 0x66, 0, 0, ...tiff]
  const bytes = [0xff, 0xd8, 0xff, 0xe1, ((app1.length + 2) >> 8) & 255, (app1.length + 2) & 255, ...app1, 0xff, 0xd9]
  return new Uint8Array(bytes).buffer
}

describe('exifDate', () => {
  it('reads DateTimeOriginal', () => expect(exifDate(jpeg('2024:02:29'))).toBe('2024-02-29'))
  it('falls back to IFD0 DateTime', () => expect(exifDate(jpeg('2023:07:04', true))).toBe('2023-07-04'))
  it('null for a zeroed date, a non-JPEG, or no EXIF', () => {
    expect(exifDate(jpeg(null))).toBeNull()
    expect(exifDate(new Uint8Array([0x89, 0x50, 0x4e, 0x47]).buffer)).toBeNull()
    expect(exifDate(new Uint8Array([0xff, 0xd8, 0xff, 0xda, 0, 2]).buffer)).toBeNull()
  })
})
