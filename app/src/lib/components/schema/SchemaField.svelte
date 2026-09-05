<script lang="ts">
	import Self from "./SchemaField.svelte";
	import { Input } from "$lib/components/ui/input";
	import { Label } from "$lib/components/ui/label";
	import { Switch } from "$lib/components/ui/switch";
	import { Badge } from "$lib/components/ui/badge";
	import { Button } from "$lib/components/ui/button";
	import * as Select from "$lib/components/ui/select";
	import { errorsForPath, type FieldError } from "$lib/schema/validate";
	import PlusIcon from "@lucide/svelte/icons/plus";
	import XIcon from "@lucide/svelte/icons/x";
	import type { JsonSchema } from "$lib/types";

	let {
		schema,
		value = $bindable(),
		label,
		pointer,
		required = false,
		errors = [],
	}: {
		schema: JsonSchema;
		value: unknown;
		label: string;
		pointer: string;
		required?: boolean;
		errors?: FieldError[];
	} = $props();

	const localErrors = $derived(errorsForPath(errors, pointer).filter((e) => e.path === pointer));

	// --- node classification -------------------------------------------------
	const typeOf = (s: JsonSchema): string =>
		Array.isArray(s.type) ? (s.type.find((t) => t !== "null") ?? "string") : (s.type ?? "");

	const kind = $derived.by(() => {
		if (schema.const !== undefined) return "const";
		if (Array.isArray(schema.oneOf)) return "oneOf";
		const t = typeOf(schema);
		if (t === "boolean") return "boolean";
		if (t === "integer" || t === "number") return "number";
		if (t === "array") return schema.items?.enum ? "enumArray" : "stringArray";
		if (t === "object")
			return schema.properties ? "object" : schema.additionalProperties ? "map" : "object";
		if (schema.enum) return "enum";
		return "string"; // includes string + pattern
	});

	const childPointer = (k: string | number) => `${pointer}/${k}`;

	// --- oneOf branch handling ----------------------------------------------
	function branchMatches(branch: JsonSchema, v: unknown): boolean {
		const t = typeOf(branch);
		if (t === "array") return Array.isArray(v);
		if (t === "object") return typeof v === "object" && v !== null && !Array.isArray(v);
		return false;
	}
	let branchIdx = $state(0);
	$effect(() => {
		const i = (schema.oneOf ?? []).findIndex((b) => branchMatches(b, value));
		if (i >= 0) branchIdx = i;
	});
	function pickBranch(i: number) {
		branchIdx = i;
		const t = typeOf((schema.oneOf ?? [])[i]);
		value = t === "array" ? [] : {};
	}
	const branchLabel = (b: JsonSchema) => {
		const t = typeOf(b);
		return t === "array" ? "list" : t === "object" ? "detailed map" : t;
	};

	// --- enum array (chips) --------------------------------------------------
	function toggleChip(option: string) {
		const arr = Array.isArray(value) ? [...(value as string[])] : [];
		value = arr.includes(option) ? arr.filter((x) => x !== option) : [...arr, option];
	}

	// --- string array (list editor) -----------------------------------------
	function addItem() {
		value = [...((value as string[]) ?? []), ""];
	}
	function setItem(i: number, v: string) {
		const arr = [...(value as string[])];
		arr[i] = v;
		value = arr;
	}
	function removeItem(i: number) {
		value = (value as string[]).filter((_, j) => j !== i);
	}

	// --- object: optional-property add UX ------------------------------------
	const obj = $derived((value ?? {}) as Record<string, unknown>);
	const definedKeys = $derived(Object.keys(schema.properties ?? {}));
	const missingOptional = $derived(
		definedKeys.filter((k) => !(k in obj) && !(schema.required ?? []).includes(k)),
	);
	function ensureObject() {
		if (typeof value !== "object" || value === null || Array.isArray(value)) value = {};
	}
	function addProperty(k: string) {
		ensureObject();
		const sub = schema.properties![k];
		(value as Record<string, unknown>)[k] = defaultFor(sub);
		value = { ...(value as object) };
	}
	function defaultFor(s: JsonSchema): unknown {
		if (s.const !== undefined) return s.const;
		const t = typeOf(s);
		if (t === "boolean") return false;
		if (t === "array") return [];
		if (t === "object") return {};
		return "";
	}

	// --- map (additionalProperties) ------------------------------------------
	const mapSchema = $derived(
		typeof schema.additionalProperties === "object"
			? (schema.additionalProperties as JsonSchema)
			: ({ type: "string" } as JsonSchema),
	);
	let newMapKey = $state("");
	function addMapEntry() {
		const k = newMapKey.trim();
		if (!k) return;
		ensureObject();
		(value as Record<string, unknown>)[k] = defaultFor(mapSchema);
		value = { ...(value as object) };
		newMapKey = "";
	}
	function removeMapEntry(k: string) {
		const next = { ...(value as Record<string, unknown>) };
		delete next[k];
		value = next;
	}
	function renderRequired(k: string) {
		return (schema.properties?.[k] && (schema.required ?? []).includes(k)) || false;
	}
</script>

<div class="flex flex-col gap-1.5">
	{#if kind !== "object" && kind !== "const"}
		<Label class="flex items-center gap-1.5 text-sm">
			{label}
			{#if required}<span class="text-destructive">*</span>{/if}
			{#if schema.description}<span class="text-muted-foreground text-xs font-normal">— {schema.description}</span>{/if}
		</Label>
	{/if}

	{#if kind === "const"}
		<div class="flex items-center gap-2 text-sm">
			<span class="text-muted-foreground">{label}:</span>
			<Badge variant="outline" class="font-mono">{String(schema.const)}</Badge>
			<span class="text-muted-foreground text-xs">(fixed)</span>
		</div>

	{:else if kind === "boolean"}
		<div class="flex items-center gap-2">
			<Switch checked={value === true} onCheckedChange={(c) => (value = c)} />
			<span class="text-muted-foreground text-xs">{value ? "true" : "false"}</span>
		</div>

	{:else if kind === "number"}
		<Input
			type="number"
			step={typeOf(schema) === "integer" ? 1 : "any"}
			value={value as number}
			oninput={(e) => (value = e.currentTarget.value === "" ? undefined : Number(e.currentTarget.value))}
		/>

	{:else if kind === "enum" || (kind === "string" && schema.enum)}
		<Select.Root type="single" value={value as string} onValueChange={(v) => (value = v)}>
			<Select.Trigger class="w-full">{(value as string) || "Select…"}</Select.Trigger>
			<Select.Content>
				{#each schema.enum ?? [] as opt (opt)}
					<Select.Item value={String(opt)}>{String(opt)}</Select.Item>
				{/each}
			</Select.Content>
		</Select.Root>

	{:else if kind === "string"}
		<Input
			value={value as string}
			placeholder={schema.pattern ? `must match ${schema.pattern}` : ""}
			oninput={(e) => (value = e.currentTarget.value)}
		/>

	{:else if kind === "enumArray"}
		<div class="flex flex-wrap gap-1.5">
			{#each schema.items?.enum ?? [] as opt (opt)}
				<button type="button" onclick={() => toggleChip(String(opt))}>
					<Badge variant={(value as string[])?.includes(String(opt)) ? "default" : "outline"}
						class="cursor-pointer">{String(opt)}</Badge>
				</button>
			{/each}
		</div>

	{:else if kind === "stringArray"}
		<div class="flex flex-col gap-1.5">
			{#each (value as string[]) ?? [] as item, i (i)}
				<div class="flex items-center gap-1.5">
					<Input value={item} oninput={(e) => setItem(i, e.currentTarget.value)} class="font-mono" />
					<Button type="button" variant="ghost" size="icon" onclick={() => removeItem(i)}>
						<XIcon class="size-4" />
					</Button>
				</div>
			{/each}
			<Button type="button" variant="outline" size="sm" class="w-fit" onclick={addItem}>
				<PlusIcon class="size-3.5" /> Add item
			</Button>
		</div>

	{:else if kind === "oneOf"}
		<div class="flex flex-col gap-3 rounded-md border p-3">
			<div class="flex items-center gap-2 text-xs">
				<span class="text-muted-foreground">Shape:</span>
				{#each schema.oneOf ?? [] as branch, i (i)}
					<button type="button" onclick={() => pickBranch(i)}>
						<Badge variant={branchIdx === i ? "default" : "outline"} class="cursor-pointer">
							{branchLabel(branch)}
						</Badge>
					</button>
				{/each}
			</div>
			<Self
				schema={(schema.oneOf ?? [])[branchIdx] ?? {}}
				bind:value
				label={label}
				{pointer}
				{errors}
			/>
		</div>

	{:else if kind === "map"}
		<div class="flex flex-col gap-2 rounded-md border p-3">
			{#each Object.keys(obj) as key (key)}
				<div class="flex flex-col gap-1.5 rounded border p-2">
					<div class="flex items-center justify-between">
						<Badge variant="secondary" class="font-mono">{key}</Badge>
						<Button type="button" variant="ghost" size="icon" class="size-7" onclick={() => removeMapEntry(key)}>
							<XIcon class="size-3.5" />
						</Button>
					</div>
					<Self
						schema={mapSchema}
						bind:value={obj[key]}
						label={key}
						pointer={childPointer(key)}
						{errors}
					/>
				</div>
			{/each}
			<div class="flex items-center gap-1.5">
				<Input bind:value={newMapKey} placeholder="new key…" class="font-mono"
					onkeydown={(e) => e.key === "Enter" && (e.preventDefault(), addMapEntry())} />
				<Button type="button" variant="outline" size="sm" onclick={addMapEntry}>
					<PlusIcon class="size-3.5" /> Add
				</Button>
			</div>
		</div>

	{:else if kind === "object"}
		<div class="flex flex-col gap-3">
			{#if label}
				<div class="text-muted-foreground text-xs font-semibold tracking-wide uppercase">{label}</div>
			{/if}
			{#each definedKeys.filter((k) => k in obj) as key (key)}
				<Self
					schema={schema.properties![key]}
					bind:value={obj[key]}
					label={key}
					pointer={childPointer(key)}
					required={renderRequired(key)}
					{errors}
				/>
			{/each}
			{#if missingOptional.length}
				<div class="flex items-center gap-1.5">
					<Select.Root type="single" value="" onValueChange={(k) => k && addProperty(k)}>
						<Select.Trigger class="h-8 w-fit text-xs">+ add field</Select.Trigger>
						<Select.Content>
							{#each missingOptional as k (k)}
								<Select.Item value={k}>{k}</Select.Item>
							{/each}
						</Select.Content>
					</Select.Root>
				</div>
			{/if}
		</div>
	{/if}

	{#each localErrors as err (err.message)}
		<p class="text-destructive text-xs">{err.message}</p>
	{/each}
</div>
