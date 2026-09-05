// The package ships no types; declare the small surface we use (see CodeEditor.svelte).
declare module "constrained-editor-plugin" {
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	export function constrainedEditor(monaco: any): {
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		initializeIn(editor: any): void;
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		addRestrictionsTo(model: any, restrictions: any[]): void;
	};
}
