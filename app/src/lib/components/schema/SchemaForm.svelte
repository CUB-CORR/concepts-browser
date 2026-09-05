<script lang="ts">
	import * as Tabs from "$lib/components/ui/tabs";
	import { Textarea } from "$lib/components/ui/textarea";
	import SchemaField from "./SchemaField.svelte";
	import type { FieldError } from "$lib/schema/validate";
	import type { JsonSchema } from "$lib/types";

	let {
		schema,
		value = $bindable(),
		errors = [],
	}: {
		schema: JsonSchema;
		value: Record<string, unknown>;
		errors?: FieldError[];
	} = $props();

	let tab = $state("form");
	let jsonText = $state("");
	let jsonError = $state("");

	function onTab(next: string) {
		tab = next;
		if (next === "json") jsonText = JSON.stringify(value, null, 2);
	}

	function applyJson(text: string) {
		jsonText = text;
		try {
			value = JSON.parse(text);
			jsonError = "";
		} catch {
			jsonError = "Not valid JSON — fix to sync back to the form.";
		}
	}
</script>

<Tabs.Root value={tab} onValueChange={onTab}>
	<Tabs.List>
		<Tabs.Trigger value="form">Form</Tabs.Trigger>
		<Tabs.Trigger value="json">JSON</Tabs.Trigger>
	</Tabs.List>

	<Tabs.Content value="form" class="pt-3">
		<div class="flex flex-col gap-4">
			<SchemaField {schema} bind:value label="" pointer="" {errors} />
		</div>
	</Tabs.Content>

	<Tabs.Content value="json" class="pt-3">
		<Textarea
			class="min-h-[280px] font-mono text-xs"
			value={jsonText}
			oninput={(e) => applyJson(e.currentTarget.value)}
		/>
		{#if jsonError}<p class="text-destructive mt-1 text-xs">{jsonError}</p>{/if}
	</Tabs.Content>
</Tabs.Root>
