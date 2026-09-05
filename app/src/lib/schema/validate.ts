import Ajv2020, { type ValidateFunction } from "ajv/dist/2020";
import type { JsonSchema } from "$lib/types";

// Live, client-side validation for the schema form. The authoritative gate is the API
// (it re-validates on create/edit/publish); this just gives instant inline feedback.
const ajv = new Ajv2020({ allErrors: true, strict: false });

export interface FieldError {
	/** JSON Pointer to the offending value, e.g. "/columns/value". "" = root. */
	path: string;
	message: string;
}

const cache = new Map<string, ValidateFunction | null>();

function compile(schema: JsonSchema): ValidateFunction | null {
	const key = schema.$id ?? JSON.stringify(schema);
	if (cache.has(key)) return cache.get(key) ?? null;
	let fn: ValidateFunction | null = null;
	try {
		// Reuse if this $id was already added (recompiling the same $id throws in ajv).
		fn = (schema.$id && ajv.getSchema(schema.$id)) || ajv.compile(schema);
	} catch {
		// Some upstream schemas use patterns that aren't valid JS RegExp (e.g. inline
		// `(?i)` flags). Rather than break the form, skip client validation for them and
		// rely on the server gate.
		fn = null;
	}
	cache.set(key, fn);
	return fn;
}

export function validate(schema: JsonSchema, data: unknown): FieldError[] {
	const fn = compile(schema);
	if (!fn) return [];
	if (fn(data)) return [];
	return (fn.errors ?? []).map((e) => ({
		path: e.instancePath,
		message: humanize(e.instancePath, e.message ?? "is invalid"),
	}));
}

/** Errors for a single field path (exact match or descendant), for inline display. */
export function errorsForPath(errors: FieldError[], path: string): FieldError[] {
	return errors.filter((e) => e.path === path || e.path.startsWith(path + "/"));
}

function humanize(pointer: string, message: string): string {
	const field = pointer ? pointer.replace(/^\//, "").replace(/\//g, ".") : "value";
	return `${field} ${message}`;
}
