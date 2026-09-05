import type { JsonSchema } from "$lib/types";

// Build a minimal config object that satisfies a leaf schema's required fields, so a brand-new
// draft passes the API's create-time validation. Users fill in the rest in the form.
const typeOf = (s: JsonSchema): string =>
	Array.isArray(s.type) ? (s.type.find((t) => t !== "null") ?? "") : (s.type ?? "");

function defaultFor(s: JsonSchema): unknown {
	if (s.const !== undefined) return s.const;
	if (Array.isArray(s.oneOf) && s.oneOf.length) return defaultFor(s.oneOf[0]);
	if (s.enum?.length) return s.enum[0];
	const t = typeOf(s);
	if (t === "boolean") return false;
	if (t === "number" || t === "integer") return 0;
	if (t === "array") return [];
	if (t === "object") return buildObject(s);
	// String: satisfy the common "must start with !" select pattern; otherwise empty.
	if (s.pattern === "^!.*$") return "!";
	return "";
}

function buildObject(schema: JsonSchema): Record<string, unknown> {
	const obj: Record<string, unknown> = {};
	for (const key of schema.required ?? []) {
		const sub = schema.properties?.[key];
		if (sub) obj[key] = defaultFor(sub);
	}
	return obj;
}

export function skeleton(schema: JsonSchema | null, fallbackType?: string): Record<string, unknown> {
	if (!schema) return fallbackType ? { type: fallbackType } : {};
	return buildObject(schema);
}
