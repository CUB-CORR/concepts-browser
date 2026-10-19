<script lang="ts">
	// Renders a guide page's parsed Markdown (see $lib/server/docs) through the components a
	// hand-written page would use, so a Markdown chapter looks exactly like the rest of the app:
	// tables are `Table.*`, code fences `CodeBlock`, links into the app `AppLink`.
	//
	// Beyond CommonMark + GFM (tables, strikethrough, autolinks), the pages may use directives:
	//
	//   :cap[can_publish]                     the "requires …" badge (`{verb="needs"}` to reword)
	//   :badge[alias]                         a badge (`{variant=secondary}`, `{mono}` for code text)
	//   :app-name                             this deployment's product name
	//   :external[the API reference]{id=api}  a link from a link group by id; plain text if absent
	//   ::data-model                          the data-model diagram
	//   ::capability-chain / ::capability-table   generated from the app's capability list
	//   ::py-template{variable=serum_creatinine}  the editor's Python template for a variable
	//   :::alert[Title]{icon=lock variant=destructive} … :::   a callout
	//   :::if{feature=issue-tracker} … :::    shown only when it holds; `:::unless` inverts.
	//                                         Also {link=<id>} (a link group defines it) and
	//                                         {cap=<capability>} (the reader holds it).
	//
	// A link to a chapter the reader may not open (admin-only, or hidden by the deployment)
	// renders as its text, never as a door into a 404. Raw HTML is dropped.
	import type { DocNode } from "$lib/docs/types";
	import { isExternalHref } from "$lib/docs/types";
	import { docIcon } from "$lib/docs/icons";
	import { page } from "$app/state";
	import { brand } from "$lib/brand";
	import { holds as holdsFor, type DirectiveAttrs } from "$lib/docs/conditions";
	import { pyTemplate } from "$lib/editor/template";
	import type { Capability } from "$lib/types";
	import * as Table from "$lib/components/ui/table";
	import * as Alert from "$lib/components/ui/alert";
	import { Badge, type BadgeVariant } from "$lib/components/ui/badge";
	import { Separator } from "$lib/components/ui/separator";
	import CodeBlock from "$lib/components/CodeBlock.svelte";
	import AppLink from "./AppLink.svelte";
	import Cap from "./Cap.svelte";
	import CapabilityChain from "./CapabilityChain.svelte";
	import CapabilityTable from "./CapabilityTable.svelte";
	import DataModelDiagram from "./DataModelDiagram.svelte";

	let { nodes }: { nodes: DocNode[] } = $props();

	/** Where a node sits: tight list items render their paragraphs inline, and links inside an
	 *  alert take the alert's colour instead of the primary one. */
	interface Ctx {
		tight: boolean;
		alert: boolean;
	}

	const ROOT: Ctx = { tight: false, alert: false };
	const LINK = "text-primary underline-offset-4 hover:underline";
	const ALERT_LINK = "underline underline-offset-4";

	const links = $derived(page.data.docs?.links ?? []);
	const slugs = $derived<string[]>(page.data.docs?.slugs ?? []);

	function holds(attrs: DirectiveAttrs): boolean {
		return holdsFor(attrs, page.data.user, links);
	}

	/** A link into a chapter this reader cannot open loses its link, keeping its words. */
	function reachable(url: string): boolean {
		const slug = /^\/docs\/([^/#?]+)/.exec(url)?.[1];
		return !slug || slugs.includes(slug);
	}

	function text(nodes: readonly DocNode[]): string {
		return nodes
			.map((n) => ("value" in n ? n.value : "children" in n ? text(n.children as DocNode[]) : ""))
			.join("");
	}

	/** A container directive's `[label]` arrives as its first paragraph, flagged as such. */
	function split(children: DocNode[]): { label: DocNode[]; rest: DocNode[] } {
		const first = children[0];
		if (first?.type === "paragraph" && first.data?.directiveLabel) {
			return { label: first.children, rest: children.slice(1) };
		}
		return { label: [], rest: children };
	}

	function cellClass(column: number): string {
		return column === 0
			? "align-top font-medium whitespace-normal"
			: "text-muted-foreground align-top text-sm whitespace-normal";
	}
</script>

{#snippet blocks(list: DocNode[], ctx: Ctx)}
	{#each list as n, i (i)}
		{@render block(n, ctx)}
	{/each}
{/snippet}

{#snippet inlines(list: DocNode[], ctx: Ctx)}{#each list as n, i (i)}{@render inline(n, ctx)}{/each}{/snippet}

{#snippet block(n: DocNode, ctx: Ctx)}
	{#if n.type === "paragraph"}
		{#if ctx.tight}{@render inlines(n.children, ctx)}{:else}<p>{@render inlines(n.children, ctx)}</p>{/if}
	{:else if n.type === "heading"}
		<h3 class="text-foreground mt-1 font-semibold">{@render inlines(n.children, ctx)}</h3>
	{:else if n.type === "list"}
		{#if n.ordered}
			<ol class="ml-4 flex list-decimal flex-col gap-1.5" start={n.start != null && n.start !== 1 ? n.start : undefined}>
				{#each n.children as item, i (i)}
					<li>{@render blocks(item.children, { ...ctx, tight: !n.spread && !item.spread })}</li>
				{/each}
			</ol>
		{:else}
			<ul class="ml-4 flex list-disc flex-col gap-1.5">
				{#each n.children as item, i (i)}
					<li>{@render blocks(item.children, { ...ctx, tight: !n.spread && !item.spread })}</li>
				{/each}
			</ul>
		{/if}
	{:else if n.type === "code"}
		<CodeBlock code={n.value} language={n.lang ?? "text"} />
	{:else if n.type === "table"}
		<Table.Root>
			<Table.Header>
				<Table.Row>
					{#each n.children[0]?.children ?? [] as cell, c (c)}
						<Table.Head>{@render inlines(cell.children, ctx)}</Table.Head>
					{/each}
				</Table.Row>
			</Table.Header>
			<Table.Body>
				{#each n.children.slice(1) as row, r (r)}
					<Table.Row>
						{#each row.children as cell, c (c)}
							<Table.Cell class={cellClass(c)}>{@render inlines(cell.children, ctx)}</Table.Cell>
						{/each}
					</Table.Row>
				{/each}
			</Table.Body>
		</Table.Root>
	{:else if n.type === "blockquote"}
		<blockquote class="border-l-2 pl-3 italic">{@render blocks(n.children, ctx)}</blockquote>
	{:else if n.type === "thematicBreak"}
		<Separator />
	{:else if n.type === "containerDirective"}
		{#if n.name === "alert"}
			{@const parts = split(n.children)}
			{@const Icon = docIcon(
				n.attributes?.icon ?? undefined,
				n.attributes?.variant === "destructive" ? "triangle-alert" : "info",
			)}
			<Alert.Root variant={n.attributes?.variant === "destructive" ? "destructive" : "default"}>
				<Icon />
				{#if parts.label.length}
					<Alert.Title>{@render inlines(parts.label, ctx)}</Alert.Title>
				{/if}
				<Alert.Description>
					{@render blocks(parts.rest, { tight: parts.rest.length === 1, alert: true })}
				</Alert.Description>
			</Alert.Root>
		{:else if n.name === "if"}
			{#if holds(n.attributes)}{@render blocks(n.children, ctx)}{/if}
		{:else if n.name === "unless"}
			{#if !holds(n.attributes)}{@render blocks(n.children, ctx)}{/if}
		{:else}
			{@render blocks(n.children, ctx)}
		{/if}
	{:else if n.type === "leafDirective"}
		{#if n.name === "data-model"}
			<DataModelDiagram />
		{:else if n.name === "capability-chain"}
			<CapabilityChain />
		{:else if n.name === "capability-table"}
			<CapabilityTable />
		{:else if n.name === "py-template"}
			<CodeBlock code={pyTemplate(n.attributes?.variable ?? "my_variable")} language="python" />
		{:else}
			<p>{@render inlines(n.children, ctx)}</p>
		{/if}
	{:else}
		{@render inline(n, ctx)}
	{/if}
{/snippet}

{#snippet inline(n: DocNode, ctx: Ctx)}
	{#if n.type === "text"}{n.value}{:else if n.type === "strong"}<strong>{@render inlines(n.children, ctx)}</strong>{:else if n.type === "emphasis"}<em>{@render inlines(n.children, ctx)}</em>{:else if n.type === "delete"}<del>{@render inlines(n.children, ctx)}</del>{:else if n.type === "inlineCode"}<code>{n.value}</code>{:else if n.type === "break"}<br />{:else if n.type === "image"}<img src={n.url} alt={n.alt ?? ""} title={n.title ?? undefined} class="max-w-full rounded-md border" />{:else if n.type === "link"}{@render link(n.url, n.children, ctx)}{:else if n.type === "textDirective"}{@render directive(n.name, n.attributes, n.children, ctx)}{/if}
{/snippet}

{#snippet link(url: string, children: DocNode[], ctx: Ctx)}
	{#if !reachable(url)}{@render inlines(children, ctx)}{:else if isExternalHref(url)}<a href={url} target="_blank" rel="noopener noreferrer" class={ctx.alert ? ALERT_LINK : LINK}>{@render inlines(children, ctx)}</a>{:else if url.startsWith("/docs") || url.startsWith("#")}<a href={url} class={ctx.alert ? ALERT_LINK : LINK}>{@render inlines(children, ctx)}</a>{:else}<AppLink href={url}>{@render inlines(children, ctx)}</AppLink>{/if}
{/snippet}

{#snippet directive(name: string, attrs: DirectiveAttrs, children: DocNode[], ctx: Ctx)}
	{#if name === "cap"}<Cap cap={text(children).trim() as Capability} verb={attrs?.verb ?? undefined} />{:else if name === "badge"}<Badge variant={(attrs?.variant ?? "outline") as BadgeVariant} class={attrs?.mono != null ? "font-mono text-xs" : undefined}>{@render inlines(children, ctx)}</Badge>{:else if name === "app-name"}{brand.appName}{:else if name === "external"}{@const target = links.find((l) => l.id === attrs?.id)}{#if target}<a href={target.href} target="_blank" rel="noopener noreferrer" class={ctx.alert ? ALERT_LINK : LINK}>{#if children.length}{@render inlines(children, ctx)}{:else}{target.label}{/if}</a>{:else}{@render inlines(children, ctx)}{/if}{:else}:{name}{@render inlines(children, ctx)}{/if}
{/snippet}

{@render blocks(nodes, ROOT)}
