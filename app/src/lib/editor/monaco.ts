// Monaco is browser-only and must be kept out of SSR — import this module lazily from
// `onMount` (see CodeEditor.svelte), never at the top level of a component that renders on
// the server. The `?worker` imports let Vite bundle the web workers; we only ever need the
// JSON language worker plus the base editor worker (Python uses Monarch highlighting, which
// has no separate worker).
//
// The lazy import below is not enough on its own: rollup *resolves* dynamic imports before it
// tree-shakes them, so the server build would still load Monaco's CSS and die on it. Keeping
// `monaco-editor` in package.json `dependencies` (not devDependencies) is what prevents that —
// adapter-node bundles devDependencies into the server and externalizes `dependencies`. Move
// it back and `pnpm build` fails on codicon.css.
import editorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";
import jsonWorker from "monaco-editor/esm/vs/language/json/json.worker?worker";

type Monaco = typeof import("monaco-editor");

let monacoPromise: Promise<Monaco> | null = null;

/** Load Monaco once, wiring its web workers. Safe to call repeatedly. */
export function loadMonaco(): Promise<Monaco> {
	if (!monacoPromise) {
		(globalThis as unknown as { MonacoEnvironment: unknown }).MonacoEnvironment = {
			getWorker(_workerId: string, label: string) {
				return label === "json" ? new jsonWorker() : new editorWorker();
			},
		};
		monacoPromise = import("monaco-editor");
	}
	return monacoPromise;
}
