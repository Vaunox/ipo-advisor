// The top-level views (left-rail navigation). Detail is a sub-view reached from a Live row.
// Order follows the IPO lifecycle: Live → Upcoming → Allotment → History.
export type View = 'live' | 'upcoming' | 'allotment' | 'history' | 'settings'
