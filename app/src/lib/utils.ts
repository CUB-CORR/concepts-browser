import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
	return twMerge(clsx(inputs));
}

/**
 * Append the active global "as of" date to an internal href so the lens follows navigation.
 * No-op when there's no active date. `date` is typically `page.url.searchParams.get("date")`.
 */
export function withDate(href: string, date: string | null | undefined): string {
	if (!date) return href;
	return `${href}${href.includes("?") ? "&" : "?"}date=${encodeURIComponent(date)}`;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type WithoutChild<T> = T extends { child?: any } ? Omit<T, "child"> : T;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type WithoutChildren<T> = T extends { children?: any } ? Omit<T, "children"> : T;
export type WithoutChildrenOrChild<T> = WithoutChildren<WithoutChild<T>>;
export type WithElementRef<T, U extends HTMLElement = HTMLElement> = T & { ref?: U | null };
