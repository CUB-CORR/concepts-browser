<script lang="ts" generics="TData, TValue">
	import type { CellContext, ColumnDefTemplate, HeaderContext } from "@tanstack/table-core";
	import { RenderComponentConfig, RenderSnippetConfig } from "./render-helpers.js";

	let {
		content,
		context,
	}: {
		content:
			| ColumnDefTemplate<HeaderContext<TData, TValue>>
			| ColumnDefTemplate<CellContext<TData, TValue>>
			| undefined;
		context: HeaderContext<TData, TValue> | CellContext<TData, TValue>;
	} = $props();
</script>

{#if typeof content === "string"}
	{content}
{:else if content}
	{@const result = content(context as never)}
	{#if result instanceof RenderComponentConfig}
		{@const { component: Comp, props } = result}
		<Comp {...props} />
	{:else if result instanceof RenderSnippetConfig}
		{@const { snippet, params } = result}
		{@render snippet(params)}
	{:else}
		{result}
	{/if}
{/if}
