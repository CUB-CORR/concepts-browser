// Python completion for the config editor, driven by the surface the vars-sync sidecar
// generates and the API serves at `GET /sources/{key}/pyapi` (shape documented in
// sync/pyapi.py). The document lists every name a `py` snippet can reach — the corr_vars
// helpers, what the snippet's scope already holds (`pl`, `pd`, `var`, `cohort`, …), and the
// members of polars/pandas — each with its signature and the first line of its docstring.
//
// What this gives you is names, signatures and docstrings. It is **not** type inference:
// nothing here knows that `var.data.lazy()` evaluates to a LazyFrame, so a chained expression
// completes to nothing rather than to a guess. Real inference means a language server
// (Pyright in WASM); until then, offering a wrong member list would be worse than offering
// none. `null` in the payload means "not retrievable" and is passed through as absent — never
// papered over with an invented signature or doc.
//
// A deployment without the sidecar 404s, and the curated fallback below keeps the editor from
// regressing to nothing.
import { formatBytes } from "$lib/format";
import type { SourceFileRecord } from "$lib/types";

type Monaco = typeof import("monaco-editor");
type Model = import("monaco-editor").editor.ITextModel;
type Position = import("monaco-editor").Position;

export interface PyMember {
	name: string;
	kind: "function" | "attribute";
	/** Parameter list including parentheses, or null when it couldn't be retrieved. */
	signature: string | null;
	returns: string | null;
	doc: string | null;
}

export interface PyType {
	doc: string | null;
	members: PyMember[];
}

export interface PyModule {
	origin: string;
	module: string;
	doc: string | null;
	functions: PyMember[];
	types: Record<string, PyType>;
}

export interface PyApi {
	generated_at?: string;
	source?: string;
	globals: PyMember[];
	modules: Record<string, PyModule>;
	context: Record<string, PyType>;
}

const attribute = (name: string, doc: string, returns: string | null = null): PyMember => ({
	name,
	kind: "attribute",
	signature: null,
	returns,
	doc,
});

// The pre-generated list, kept as the floor: a deployment with no vars-sync sidecar has no
// pyapi.json, and an editor that completes nothing at all would be a regression.
const FALLBACK: PyApi = {
	globals: [
		attribute("var", "the variable being defined"),
		attribute("cohort", "the cohort context"),
		attribute("pl", "module polars", "polars"),
		attribute("pd", "module pandas", "pandas"),
		attribute("np", "module numpy", "numpy"),
		{
			name: "getfile",
			kind: "function",
			signature: "(uuid)",
			returns: "pathlib.Path",
			doc: "path to a data file from this source's library, by uuid",
		},
	],
	modules: {},
	context: {
		var: {
			doc: "the variable being defined",
			members: [
				attribute("data", "the output dataframe — assign your result here"),
			],
		},
		cohort: {
			doc: "the cohort context",
			members: [
				{
					name: "add_variable",
					kind: "function",
					signature: "(name)",
					returns: null,
					doc: "pull another variable into scope",
				},
			],
		},
	},
};

// --- fetching -------------------------------------------------------------------------------

// One in-flight request per source, ever: the document is ~250 KB and completion runs on every
// keystroke. Failures are cached too — a deployment without the sidecar must not be re-asked
// each time an editor mounts.
const surfaces = new Map<string, Promise<PyApi>>();

function loadSurface(source: string): Promise<PyApi> {
	let pending = surfaces.get(source);
	if (!pending) {
		pending = fetch(`/concepts/pyapi/${encodeURIComponent(source)}`)
			.then((res) => (res.ok ? (res.json() as Promise<PyApi>) : FALLBACK))
			.then((api) => ({
				globals: api.globals ?? [],
				modules: api.modules ?? {},
				context: api.context ?? {},
				generated_at: api.generated_at,
				source: api.source,
			}))
			.catch(() => FALLBACK);
		surfaces.set(source, pending);
	}
	return pending;
}

// The source's file library, cached the same way and for the same reason: `getfile("…")`
// completion runs on every keystroke inside the string, and the diagnostic pass re-reads the
// list on every edit.
const fileLists = new Map<string, Promise<SourceFileRecord[] | null>>();

/** The files of one source, or `null` when they could not be read. `null` is not `[]`: an
 *  empty library means every uuid is unknown, while an unreadable one means nothing is known,
 *  and the editor must not mark a snippet wrong on the strength of a failed request. */
export function loadSourceFiles(source: string): Promise<SourceFileRecord[] | null> {
	let pending = fileLists.get(source);
	if (!pending) {
		pending = fetch(`/concepts/files/${encodeURIComponent(source)}`)
			.then((res) => (res.ok ? (res.json() as Promise<SourceFileRecord[]>) : null))
			.catch(() => null);
		fileLists.set(source, pending);
	}
	return pending;
}

/** Forget a source's cached library — after an upload, so the picker and the markers see the
 *  new file without a reload. */
export function invalidateSourceFiles(source: string): void {
	fileLists.delete(source);
}

// Which surface a given editor completes against, keyed by model URI: two editors on one page
// may belong to different sources, and a provider is registered globally per Monaco.
const bound = new Map<string, PyApi>();
const boundFiles = new Map<string, SourceFileRecord[] | null>();

/** Point one editor model at a source's completion surface. Starts on the curated fallback
 *  and swaps in the generated one when it arrives, so the editor is never dead while the
 *  document downloads. Returns a disposer for the model's lifetime. */
export function bindPythonSurface(model: Model, source: string): () => void {
	const key = model.uri.toString();
	bound.set(key, FALLBACK);
	boundFiles.set(key, null);
	loadSurface(source).then((api) => {
		if (bound.has(key)) bound.set(key, api);
	});
	loadSourceFiles(source).then((files) => {
		if (!boundFiles.has(key)) return;
		boundFiles.set(key, files);
		markUnknownFiles(model);
	});

	// The uuids in the text change as it is typed, so the marker pass follows every edit.
	const listener = model.onDidChangeContent(() => markUnknownFiles(model));

	return () => {
		listener.dispose();
		bound.delete(key);
		boundFiles.delete(key);
		monacoRef?.editor.setModelMarkers(model, MARKER_OWNER, []);
	};
}

const surfaceOf = (model: Model): PyApi => bound.get(model.uri.toString()) ?? FALLBACK;
const filesOf = (model: Model): SourceFileRecord[] | null => boundFiles.get(model.uri.toString()) ?? null;

// --- resolving what a prefix completes to ---------------------------------------------------

type Entry = {
	name: string;
	/** How to render it; `member` defers to the member's own function/attribute kind. */
	role: "module" | "type" | "member";
	member: PyMember;
};

const member = (m: PyMember): Entry => ({ name: m.name, role: "member", member: m });

/** Everything offered for a bare identifier: the snippet's globals, the module aliases it can
 *  reach, and the two arguments it is handed. */
function rootEntries(api: PyApi): Entry[] {
	const out: Entry[] = [];
	for (const [alias, mod] of Object.entries(api.modules)) {
		// `utils.time` is reachable, but only ever written after `utils.` — not bare.
		if (alias.includes(".")) continue;
		out.push({
			name: alias,
			role: "module",
			member: attribute(alias, mod.doc ?? `module ${mod.module}`, mod.module),
		});
	}
	for (const [name, ctx] of Object.entries(api.context)) {
		out.push({ name, role: "member", member: attribute(name, ctx.doc ?? "") });
	}
	out.push(...api.globals.map(member));
	return dedupe(out);
}

/** What `<qualifier>.` completes to, or an empty list when nothing is known about it — which
 *  is the honest answer for a chained expression. */
function entriesFor(api: PyApi, qualifier: string): Entry[] {
	const mod = api.modules[qualifier];
	if (mod) {
		const out: Entry[] = mod.functions.map(member);
		for (const [name, type] of Object.entries(mod.types)) {
			out.push({ name, role: "type", member: attribute(name, type.doc ?? "") });
		}
		// Submodules folded under a package alias (`utils.` → `time`).
		const prefix = `${qualifier}.`;
		for (const [alias, sub] of Object.entries(api.modules)) {
			if (alias.startsWith(prefix) && !alias.slice(prefix.length).includes(".")) {
				const name = alias.slice(prefix.length);
				out.push({
					name,
					role: "module",
					member: attribute(name, sub.doc ?? `module ${sub.module}`, sub.module),
				});
			}
		}
		return dedupe(out);
	}

	const ctx = api.context[qualifier];
	if (ctx) return dedupe(ctx.members.map(member));

	// A type written out in full (`pl.DataFrame.`) — the name is literally in the payload, so
	// this is a lookup, not an inference.
	const dot = qualifier.lastIndexOf(".");
	if (dot > 0) {
		const type = api.modules[qualifier.slice(0, dot)]?.types[qualifier.slice(dot + 1)];
		if (type) return dedupe(type.members.map(member));
	}
	return [];
}

function dedupe(entries: Entry[]): Entry[] {
	const seen = new Set<string>();
	return entries.filter((e) => !seen.has(e.name) && seen.add(e.name));
}

function lookup(api: PyApi, dotted: string): PyMember | null {
	const dot = dotted.lastIndexOf(".");
	const pool = dot < 0 ? rootEntries(api) : entriesFor(api, dotted.slice(0, dot));
	const name = dot < 0 ? dotted : dotted.slice(dot + 1);
	return pool.find((e) => e.name === name)?.member ?? null;
}

// --- reading the source text ------------------------------------------------------------------

/** Blank out string literals and comments, keeping every offset intact, so bracket matching
 *  and the qualifier regex don't trip over punctuation inside a quoted path. */
function mask(text: string): string {
	return text
		.replace(/(['"])(?:\\.|(?!\1)[^\n])*\1?/g, (s) => " ".repeat(s.length))
		.replace(/#[^\n]*/g, (s) => " ".repeat(s.length));
}

const QUALIFIER = /([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\.\w*$/;

/** The dotted prefix the cursor sits behind: null for a bare identifier, the prefix itself for
 *  `pl.`/`utils.time.`/`var.`, and `""` for a dot hanging off something that isn't a plain
 *  dotted name (`var.data.lazy().`) — which resolves to no members at all, because working out
 *  what that expression evaluates to is exactly the inference this doesn't do. */
function qualifierAt(model: Model, position: Position): string | null {
	const line = mask(
		model.getValueInRange({
			startLineNumber: position.lineNumber,
			startColumn: 1,
			endLineNumber: position.lineNumber,
			endColumn: position.column,
		}),
	);
	if (!/\.\w*$/.test(line)) return null;
	return QUALIFIER.exec(line)?.[1] ?? "";
}

/** The call the cursor is inside: the callee's dotted name and which argument it is on. */
function callAt(model: Model, position: Position): { name: string; argument: number } | null {
	const text = mask(
		model.getValueInRange({
			startLineNumber: Math.max(1, position.lineNumber - 20),
			startColumn: 1,
			endLineNumber: position.lineNumber,
			endColumn: position.column,
		}),
	);
	let depth = 0;
	let argument = 0;
	for (let i = text.length - 1; i >= 0; i--) {
		const ch = text[i];
		if (ch === ")" || ch === "]" || ch === "}") depth++;
		else if (ch === "(" || ch === "[" || ch === "{") {
			if (depth > 0) {
				depth--;
				continue;
			}
			// An unmatched opener at this level: only `(` is a call, and only if a name
			// precedes it (`(a, b)` is a tuple).
			if (ch !== "(") return null;
			const name = /([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)$/.exec(text.slice(0, i))?.[1];
			return name ? { name, argument } : null;
		} else if (ch === "," && depth === 0) {
			argument++;
		}
		// Newlines are not a boundary: an unclosed `(` is exactly what lets a Python call span
		// lines, and scanning backwards we meet the arguments before we meet the paren.
	}
	return null;
}

/** Split a signature's parameter list, with each parameter's offsets inside the string, so
 *  the active one can be highlighted precisely rather than by substring search. */
function parameters(signature: string): { text: string; start: number; end: number }[] {
	const masked = mask(signature);
	const out: { text: string; start: number; end: number }[] = [];
	let depth = 0;
	let start = 1;
	const push = (end: number) => {
		const raw = signature.slice(start, end);
		const lead = raw.length - raw.trimStart().length;
		const text = raw.trim();
		if (text) out.push({ text, start: start + lead, end: start + lead + text.length });
	};
	for (let i = 1; i < masked.length - 1; i++) {
		const ch = masked[i];
		if (ch === "(" || ch === "[" || ch === "{") depth++;
		else if (ch === ")" || ch === "]" || ch === "}") depth--;
		else if (ch === "," && depth === 0) {
			push(i);
			start = i + 1;
		}
	}
	push(masked.length - 1);
	return out;
}

// --- getfile("uuid") --------------------------------------------------------------------------

// A data file is reached by uuid, not by name, which is what lets it be replaced without
// touching a single snippet — and also what makes a bare `getfile("2f3a…")` unreadable and
// impossible to type from memory. So the editor does both halves: it completes the uuid from
// the file's path, and it says so when a uuid names nothing in this source.

/** The `getfile("` the cursor is sitting inside, with whatever has been typed of the uuid. */
const GETFILE_OPEN = /getfile\(\s*(['"])([^'"\n]*)$/;

/** A complete `getfile("…")` call, for the marker pass. */
const GETFILE_CALL = /getfile\(\s*(['"])([^'"\n]*)\1\s*\)/g;

function getfileArgAt(model: Model, position: Position): { typed: string } | null {
	const line = model.getValueInRange({
		startLineNumber: position.lineNumber,
		startColumn: 1,
		endLineNumber: position.lineNumber,
		endColumn: position.column,
	});
	const hit = GETFILE_OPEN.exec(line);
	return hit ? { typed: hit[2] } : null;
}

const MARKER_OWNER = "getfile";

/** Set by `registerPythonExtras`; the marker pass needs the namespace and only editors that
 *  registered the providers ever bind a surface. */
let monacoRef: Monaco | null = null;

/** Flag every `getfile("…")` whose uuid is not in this source's library. Silent while the
 *  library is unknown — an unreadable list is not evidence that a snippet is wrong. */
function markUnknownFiles(model: Model): void {
	const monaco = monacoRef;
	const files = filesOf(model);
	if (!monaco || model.isDisposed()) return;
	if (!files) return;

	const known = new Set(files.map((f) => f.uuid));
	const text = model.getValue();
	const markers = [];
	GETFILE_CALL.lastIndex = 0;
	let hit: RegExpExecArray | null;
	while ((hit = GETFILE_CALL.exec(text)) !== null) {
		const uuid = hit[2];
		if (known.has(uuid)) continue;
		// Point at the uuid itself, not at the whole call.
		const offset = hit.index + hit[0].indexOf(hit[1]) + 1;
		const start = model.getPositionAt(offset);
		const end = model.getPositionAt(offset + uuid.length);
		markers.push({
			severity: monaco.MarkerSeverity.Error,
			message: uuid
				? `No file with uuid ${uuid} in this source. Pick one from the file library.`
				: "getfile() needs the uuid of a file in this source's library.",
			startLineNumber: start.lineNumber,
			startColumn: start.column,
			endLineNumber: end.lineNumber,
			endColumn: Math.max(end.column, start.column + 1),
		});
	}
	monaco.editor.setModelMarkers(model, MARKER_OWNER, markers);
}

// --- Monaco providers -------------------------------------------------------------------------

let registered = false;

/** Register the Python completion and signature-help providers once per Monaco instance. Each
 *  editor then binds its own surface with `bindPythonSurface`. */
export function registerPythonExtras(monaco: Monaco): void {
	monacoRef = monaco;
	if (registered) return;
	registered = true;

	const kinds = monaco.languages.CompletionItemKind;

	monaco.languages.registerCompletionItemProvider("python", {
		triggerCharacters: [".", '"', "'"],
		provideCompletionItems(model, position) {
			// Inside `getfile("…")` the only thing that belongs is a uuid from this source's
			// library — listed by path, because that is what a person recognises.
			const arg = getfileArgAt(model, position);
			if (arg) {
				const files = filesOf(model) ?? [];
				const range = {
					startLineNumber: position.lineNumber,
					endLineNumber: position.lineNumber,
					startColumn: position.column - arg.typed.length,
					endColumn: position.column,
				};
				return {
					suggestions: [...files]
						.sort((a, b) => a.path.localeCompare(b.path))
						.map((file) => ({
							label: file.path,
							kind: kinds.File,
							// Typing either half finds it: the path is what is remembered, the uuid
							// is what is already on the line when an existing call is being edited.
							filterText: `${file.path} ${file.uuid}`,
							insertText: file.uuid,
							detail: `v${file.version_no} · ${formatBytes(file.size)}`,
							documentation: file.uuid,
							range,
						})),
				};
			}

			const api = surfaceOf(model);
			const qualifier = qualifierAt(model, position);
			const entries = qualifier === null ? rootEntries(api) : entriesFor(api, qualifier);

			const word = model.getWordUntilPosition(position);
			const range = {
				startLineNumber: position.lineNumber,
				endLineNumber: position.lineNumber,
				startColumn: word.startColumn,
				endColumn: word.endColumn,
			};

			return {
				suggestions: entries.map((entry) => {
					const m = entry.member;
					const callable = entry.role === "member" && m.kind === "function";
					return {
						label: entry.name,
						kind:
							entry.role === "module"
								? kinds.Module
								: entry.role === "type"
									? kinds.Class
									: callable
										? kinds.Function
										: qualifier === null
											? kinds.Variable
											: kinds.Field,
						// Land inside the parens and pop the signature straight away.
						insertText: callable ? `${entry.name}($1)` : entry.name,
						insertTextRules: callable
							? monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet
							: undefined,
						command: callable
							? { id: "editor.action.triggerParameterHints", title: "" }
							: undefined,
						// Whatever the payload knows, and nothing more: an unretrievable
						// signature simply shows no detail.
						detail: m.signature ?? m.returns ?? undefined,
						documentation: m.doc ?? undefined,
						range,
					};
				}),
			};
		},
	});

	monaco.languages.registerSignatureHelpProvider("python", {
		signatureHelpTriggerCharacters: ["(", ","],
		signatureHelpRetriggerCharacters: [",", ")"],
		provideSignatureHelp(model, position) {
			const call = callAt(model, position);
			if (!call) return null;
			const found = lookup(surfaceOf(model), call.name);
			// No signature in the payload means it could not be retrieved upstream; say
			// nothing rather than render an empty parameter list as if it took none.
			if (!found?.signature) return null;

			const label = `${call.name}${found.signature}`;
			const offset = call.name.length;
			const params = parameters(found.signature);
			return {
				value: {
					signatures: [
						{
							label,
							documentation: found.doc ?? undefined,
							parameters: params.map((p) => ({
								label: [offset + p.start, offset + p.end] as [number, number],
							})),
						},
					],
					activeSignature: 0,
					activeParameter: Math.min(call.argument, Math.max(params.length - 1, 0)),
				},
				dispose() {},
			};
		},
	});
}
