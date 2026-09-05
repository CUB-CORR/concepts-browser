// The shadcn-svelte data-table render helpers. A TanStack column definition's `header`/`cell`
// is a plain function returning "content"; in Svelte that content is a component or a snippet,
// which cannot be returned directly. These two wrappers box one of each so `<FlexRender>` can
// tell them apart from a string at render time.
import type { Component, ComponentProps, Snippet } from "svelte";

export class RenderComponentConfig<TComponent extends Component> {
	constructor(
		public component: TComponent,
		public props: ComponentProps<TComponent> | Record<string, never> = {},
	) {}
}

export function renderComponent<
	TComponent extends Component,
	TProps extends ComponentProps<TComponent>,
>(component: TComponent, props: TProps = {} as TProps) {
	return new RenderComponentConfig(component, props);
}

export class RenderSnippetConfig<TProps> {
	constructor(
		public snippet: Snippet<[TProps]>,
		public params: TProps,
	) {}
}

export function renderSnippet<TProps>(snippet: Snippet<[TProps]>, params: TProps) {
	return new RenderSnippetConfig(snippet, params);
}
