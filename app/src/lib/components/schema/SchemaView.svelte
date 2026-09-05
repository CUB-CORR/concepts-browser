<script lang="ts">
	import Self from "./SchemaView.svelte";
	import { Badge } from "$lib/components/ui/badge";
	import * as Tooltip from "$lib/components/ui/tooltip";
	import { cn } from "$lib/utils";
	import CheckIcon from "@lucide/svelte/icons/check";
	import XIcon from "@lucide/svelte/icons/x";
	import type { JsonSchema } from "$lib/types";

	let {
		schema = null,
		value,
		label,
		pointer = "",
	}: {
		schema: JsonSchema | null;
		value: unknown;
		label?: string;
		pointer?: string;
	} = $props();

	// --- node classification (mirrors SchemaField logic) -----------------------
	const typeOf = (s: JsonSchema): string =>
		Array.isArray(s.type) ? (s.type.find((t) => t !== "null") ?? "string") : (s.type ?? "");

	const kind = $derived.by((): string => {
		if (schema === null) return "raw";
		if (schema.const !== undefined) return "const";
		if (Array.isArray(schema.oneOf)) return "oneOf";
		const t = typeOf(schema);
		if (t === "boolean") return "boolean";
		if (t === "integer" || t === "number") return "number";
		if (t === "array") return schema.items?.enum ? "enumArray" : "stringArray";
		if (t === "object")
			return schema.properties ? "object" : schema.additionalProperties ? "map" : "object";
		if (schema.enum) return "enum";
		return "string";
	});

	const childPointer = (k: string | number) => `${pointer}/${k}`;

	// --- oneOf branch resolution -----------------------------------------------
	function branchMatches(branch: JsonSchema, v: unknown): boolean {
		const t = typeOf(branch);
		if (t === "array") return Array.isArray(v);
		if (t === "object") return typeof v === "object" && v !== null && !Array.isArray(v);
		return false;
	}

	const resolvedBranch = $derived.by((): JsonSchema | null => {
		if (schema === null || !Array.isArray(schema.oneOf)) return null;
		return (
			schema.oneOf.find((b) => branchMatches(b, value as unknown)) ?? schema.oneOf[0] ?? null
		);
	});

	// --- map schema ------------------------------------------------------------
	const mapSchema = $derived.by((): JsonSchema => {
		if (
			schema !== null &&
			typeof schema.additionalProperties === "object" &&
			schema.additionalProperties !== null &&
			!Array.isArray(schema.additionalProperties)
		) {
			return schema.additionalProperties as JsonSchema;
		}
		return { type: "string" } as JsonSchema;
	});

	// --- object properties to show (only keys present in value) ---------------
	const obj = $derived(
		(typeof value === "object" && value !== null && !Array.isArray(value)
			? value
			: {}) as Record<string, unknown>,
	);

	const propertyKeys = $derived.by((): string[] => {
		if (schema?.properties) {
			// Show schema-ordered keys that exist in value
			return Object.keys(schema.properties).filter((k) => k in obj);
		}
		return [];
	});

	// --- label/title resolution ------------------------------------------------
	const displayLabel = $derived(schema?.title ?? label ?? "");

	// --- humanise a raw key as a label (snake_case → Title Case) --------------
	function humanise(key: string): string {
		return key
			.replace(/_/g, " ")
			.replace(/\b\w/g, (c) => c.toUpperCase());
	}

	// --- raw fallback rendering ------------------------------------------------
	function rawKind(v: unknown): "object" | "array" | "scalar" {
		if (Array.isArray(v)) return "array";
		if (typeof v === "object" && v !== null) return "object";
		return "scalar";
	}
</script>

<!--
	Label with its schema description tucked into a hover tooltip rather than
	printed inline. A faint dotted underline is the only affordance — no icon,
	no inline text, so the field rows stay uncluttered.
-->
{#snippet fieldLabel(text: string, cls: string)}
	{#if schema?.description}
		<Tooltip.Root>
			<Tooltip.Trigger>
				{#snippet child({ props })}
					<span
						{...props}
						class={cn(
							cls,
							"decoration-muted-foreground/30 cursor-help underline decoration-dotted underline-offset-2",
						)}>{text}</span
					>
				{/snippet}
			</Tooltip.Trigger>
			<Tooltip.Content>{schema.description}</Tooltip.Content>
		</Tooltip.Root>
	{:else}
		<span class={cls}>{text}</span>
	{/if}
{/snippet}

<!--
	Top-level wrapper: for "object" and "map" kinds the container itself is a
	section with a heading; for leaf kinds it's a compact label+value row.
-->
{#if kind === "object"}
	<div class="flex flex-col gap-0">
		{#if displayLabel}
			<div class="mb-1.5 flex items-baseline gap-1.5">
				{@render fieldLabel(
					displayLabel,
					"text-xs font-semibold tracking-wide text-foreground uppercase",
				)}
			</div>
		{/if}
		<div class="flex flex-col gap-2 border-l border-border pl-3">
			{#each propertyKeys as key (key)}
				<Self
					schema={schema?.properties?.[key] ?? null}
					value={obj[key] as Record<string, unknown>}
					label={schema?.properties?.[key]?.title ?? humanise(key)}
					pointer={childPointer(key)}
				/>
			{/each}
		</div>
	</div>

{:else if kind === "map"}
	<div class="flex flex-col gap-0">
		{#if displayLabel}
			<div class="mb-1.5 flex items-baseline gap-1.5">
				{@render fieldLabel(
					displayLabel,
					"text-xs font-semibold tracking-wide text-foreground uppercase",
				)}
			</div>
		{/if}
		<div class="flex flex-col gap-1.5">
			{#each Object.keys(obj) as key (key)}
				<div class="rounded-md border border-border bg-muted/30 px-2.5 py-2">
					<div class="mb-1 flex items-center gap-1.5">
						<Badge variant="secondary" class="font-mono text-xs">{key}</Badge>
					</div>
					<div class="pl-1">
						<Self
							schema={mapSchema}
							value={obj[key] as Record<string, unknown>}
							label={key}
							pointer={childPointer(key)}
						/>
					</div>
				</div>
			{/each}
		</div>
	</div>

{:else if kind === "oneOf"}
	{#if resolvedBranch !== null}
		<Self
			schema={resolvedBranch}
			{value}
			{label}
			pointer={childPointer("oneOf")}
		/>
	{/if}

{:else}
	<!-- Leaf field: label row + value -->
	<div class="flex flex-col gap-0.5">
		{#if displayLabel}
			<div class="flex items-baseline gap-1.5">
				{@render fieldLabel(displayLabel, "text-xs font-medium text-muted-foreground")}
			</div>
		{/if}

		<div class="text-sm">
			{#if kind === "const"}
				<div class="flex items-center gap-1.5">
					<span class="font-mono text-xs text-foreground">{String(schema?.const ?? value)}</span>
					<span class="text-muted-foreground text-xs">(fixed)</span>
				</div>

			{:else if kind === "boolean"}
				{#if value === true}
					<div class="flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
						<CheckIcon class="size-3.5" />
						<span class="text-xs font-medium">true</span>
					</div>
				{:else}
					<div class="flex items-center gap-1 text-muted-foreground">
						<XIcon class="size-3.5" />
						<span class="text-xs font-medium">false</span>
					</div>
				{/if}

			{:else if kind === "number"}
				<span class="font-mono text-sm text-foreground">{value}</span>

			{:else if kind === "enum"}
				<Badge variant="secondary">{String(value)}</Badge>

			{:else if kind === "string"}
				{#if schema?.pattern || (typeof value === "string" && value.startsWith("!"))}
					<code class="rounded bg-muted px-1 py-0.5 font-mono text-xs text-foreground"
						>{value}</code
					>
				{:else}
					<span class="text-sm text-foreground">{value}</span>
				{/if}

			{:else if kind === "enumArray"}
				{#if Array.isArray(value) && (value as string[]).length > 0}
					<div class="flex flex-wrap gap-1">
						{#each value as string[] as chip (chip)}
							<Badge variant="outline" class="text-xs">{chip}</Badge>
						{/each}
					</div>
				{:else}
					<span class="text-muted-foreground text-xs italic">none</span>
				{/if}

			{:else if kind === "stringArray"}
				{#if Array.isArray(value) && (value as unknown[]).length > 0}
					<ul class="flex flex-col gap-0.5">
						{#each value as unknown[] as item, i (i)}
							<li class="flex items-start gap-1.5 text-xs">
								<span class="text-muted-foreground select-none">·</span>
								<code class="font-mono text-foreground">{String(item)}</code>
							</li>
						{/each}
					</ul>
				{:else}
					<span class="text-muted-foreground text-xs italic">empty list</span>
				{/if}

			{:else if kind === "raw"}
				<!-- schema is null: sensible fallback without JSON.stringify -->
				{#if rawKind(value) === "array"}
					{#if (value as unknown[]).length === 0}
						<span class="text-muted-foreground text-xs italic">empty list</span>
					{:else}
						<ul class="flex flex-col gap-0.5">
							{#each value as unknown[] as item, i (i)}
								<li class="flex items-start gap-1.5 text-xs">
									<span class="text-muted-foreground select-none">·</span>
									{#if typeof item === "object" && item !== null}
										<div class="flex flex-col gap-0.5">
											{#each Object.entries(item as Record<string, unknown>) as [k, v] (k)}
												<span>
													<span class="text-muted-foreground">{humanise(k)}:</span>
													<code class="ml-1 font-mono text-xs text-foreground">{String(v)}</code>
												</span>
											{/each}
										</div>
									{:else}
										<code class="font-mono text-foreground">{String(item)}</code>
									{/if}
								</li>
							{/each}
						</ul>
					{/if}
				{:else if rawKind(value) === "object"}
					<div class="flex flex-col gap-1 border-l border-border pl-3">
						{#each Object.entries(obj) as [k, v] (k)}
							<div class="flex items-baseline gap-1.5 text-xs">
								<span class="font-medium text-muted-foreground">{humanise(k)}:</span>
								{#if typeof v === "boolean"}
									{#if v}
										<span class="text-emerald-600 dark:text-emerald-400 font-medium">true</span>
									{:else}
										<span class="text-muted-foreground font-medium">false</span>
									{/if}
								{:else if typeof v === "object" && v !== null}
									<code class="font-mono text-xs text-muted-foreground">[object]</code>
								{:else}
									<code class="font-mono text-foreground">{String(v)}</code>
								{/if}
							</div>
						{/each}
					</div>
				{:else}
					<!-- scalar raw -->
					{#if typeof value === "boolean"}
						{#if value}
							<div class="flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
								<CheckIcon class="size-3.5" />
								<span class="text-xs font-medium">true</span>
							</div>
						{:else}
							<div class="flex items-center gap-1 text-muted-foreground">
								<XIcon class="size-3.5" />
								<span class="text-xs font-medium">false</span>
							</div>
						{/if}
					{:else}
						<span class="text-sm text-foreground">{String(value)}</span>
					{/if}
				{/if}
			{/if}
		</div>
	</div>
{/if}
