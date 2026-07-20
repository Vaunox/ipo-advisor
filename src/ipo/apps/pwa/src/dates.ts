// Tz-safe handling of DATE-ONLY values — the server `date` fields (open_date / close_date /
// listing_date, serialized as `YYYY-MM-DD`). `new Date("2026-07-16")` parses as midnight UTC and then
// renders in the browser's local zone, so a browser behind UTC (the Americas) shows the PREVIOUS day.
// Appending a bare `T00:00:00` (no offset) makes the engine parse it as LOCAL midnight — the ES2015
// rule for a date-time string without a timezone — so it renders as the intended calendar day in any
// browser tz. This is the same local-midnight idiom `midnight()` (status.ts) already uses.
//
// This is the ONE home for the pattern: date-only display sites format via `formatDateOnly`, so the
// bug-class cannot silently reappear as a private `new Date(iso)` copy. DATETIME values
// (refreshed_at / captured_at / asof) must NOT use this — they carry a time + offset and parse
// unambiguously, so `new Date(that)` is already correct.

/** Parse a date-only `YYYY-MM-DD` as LOCAL midnight (tz-safe — see file header). */
export function parseDateOnly(iso: string): Date {
  return new Date(iso + 'T00:00:00')
}

/** Format a date-only `YYYY-MM-DD` for display in any browser tz (tz-safe — see file header). */
export function formatDateOnly(iso: string, opts: Intl.DateTimeFormatOptions): string {
  return parseDateOnly(iso).toLocaleDateString('en-IN', opts)
}
