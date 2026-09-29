/** Monday (YYYY-MM-DD) of the week containing `date`. Pure calendar math on the date string, no timezone drift. */
export function mondayOf(date: string): string {
  const [y, m, d] = date.split('-').map(Number)
  const t = new Date(Date.UTC(y, m - 1, d))
  const back = (t.getUTCDay() + 6) % 7 // Mon=0 ... Sun=6
  t.setUTCDate(t.getUTCDate() - back)
  return t.toISOString().slice(0, 10)
}
/** Is `date` within the week that starts on `monday`? */
export const inWeek = (date: string, monday: string) => mondayOf(date) === monday

export interface WeeklyPayload { eventId?: string; taskId?: string; dreamId?: string; stepTitle?: string }
