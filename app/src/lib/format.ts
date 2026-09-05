// The API stores naive-UTC timestamps (SQLite has no tz); render them as UTC so they don't
// silently shift by the viewer's offset.
export function formatTimestamp(value: string | null | undefined): string {
	if (!value) return "—";
	const iso = /[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`;
	const d = new Date(iso);
	if (isNaN(d.getTime())) return value;
	return new Intl.DateTimeFormat("en-CA", {
		year: "numeric",
		month: "2-digit",
		day: "2-digit",
		hour: "2-digit",
		minute: "2-digit",
		hour12: false,
		timeZone: "UTC",
	}).format(d) + " UTC";
}

// Binary units (what a file manager shows), one decimal from KB up, so a 5654-byte mapping
// table reads "5.5 KB" instead of a raw byte count.
const BYTE_UNITS = ["B", "KB", "MB", "GB", "TB"];

/** A byte count as a short human-readable size. */
export function formatBytes(bytes: number): string {
	if (!Number.isFinite(bytes) || bytes < 0) return "—";
	let value = bytes;
	let unit = 0;
	while (value >= 1024 && unit < BYTE_UNITS.length - 1) {
		value /= 1024;
		unit += 1;
	}
	return `${unit === 0 ? value : value.toFixed(1)} ${BYTE_UNITS[unit]}`;
}

/** The app-side path for one source file. Files belong to the source, not to a concept, so the
 *  address is (source, uuid) — the same identity the snippet spells `getfile("<uuid>")`. */
export function filePageHref(source: string, uuid: string): string {
	return `/files/${encodeURIComponent(source)}/${encodeURIComponent(uuid)}`;
}

/** The download proxy for one source file. The browser can't call the API directly (the bearer
 *  token never leaves the server), so bytes go through the app route. A `version` pins the
 *  download to exactly that version; without one the API serves the current bytes. */
export function fileDownloadHref(source: string, uuid: string, version?: number | null): string {
	const base = `${filePageHref(source, uuid)}/download`;
	return version == null ? base : `${base}?version=${version}`;
}

/** The accessor a `py` snippet reaches a file by. */
export function getfileRef(uuid: string): string {
	return `getfile(${JSON.stringify(uuid)})`;
}

const CHANGE_TYPE_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
	initial: "secondary",
	improvement: "outline",
	critical: "destructive",
};

export function changeTypeVariant(changeType: string): "default" | "secondary" | "destructive" | "outline" {
	return CHANGE_TYPE_VARIANT[changeType] ?? "outline";
}
