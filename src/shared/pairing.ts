/** A new code is needed only when none is showing or the current one is near its 10-minute expiry. */
export const CODE_REFRESH_MS = 9 * 60_000
export const shouldIssueCode = (current: string | null, issuedAt: number, now: number) => !current || now - issuedAt > CODE_REFRESH_MS

/** Retry delays after a failed boot (e.g. TV started before Wi-Fi): 5s, 15s, 30s, then every 60s. */
export const BOOT_BACKOFF_MS = [5_000, 15_000, 30_000, 60_000]
export const backoffDelay = (attempt: number) => BOOT_BACKOFF_MS[Math.min(attempt, BOOT_BACKOFF_MS.length - 1)]
