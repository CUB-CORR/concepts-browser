<script lang="ts">
	import { goto } from "$app/navigation";
	import { page } from "$app/state";
	import { Button, buttonVariants } from "$lib/components/ui/button";
	import { Calendar } from "$lib/components/ui/calendar";
	import * as Popover from "$lib/components/ui/popover";
	import { cn } from "$lib/utils";
	import {
		DateFormatter,
		getLocalTimeZone,
		parseDate,
		today,
		type DateValue,
	} from "@internationalized/date";
	import CalendarIcon from "@lucide/svelte/icons/calendar";
	import XIcon from "@lucide/svelte/icons/x";

	let { value }: { value: string } = $props();

	const df = new DateFormatter("en-US", { dateStyle: "medium" });

	// Mirror the URL-provided "YYYY-MM-DD" (or "") into a DateValue for the calendar.
	let selected = $derived<DateValue | undefined>(value ? parseDate(value) : undefined);
	let open = $state(false);

	// The global "as of date" filter lives in the URL (?date=). Setting it applies the lens to
	// the current page; clearing it (next === "") removes the param and returns to live.
	function apply(next: string) {
		const url = new URL(page.url);
		if (next) url.searchParams.set("date", next);
		else url.searchParams.delete("date");
		url.searchParams.delete("d");
		goto(url, { invalidateAll: true, keepFocus: true });
	}
</script>

<div class="flex items-center gap-1">
	<Popover.Root bind:open>
		<Popover.Trigger
			class={cn(
				buttonVariants({ variant: "outline", size: "sm" }),
				"w-[170px] justify-start text-left font-normal",
				!value && "text-muted-foreground",
			)}
			aria-label="View as of date"
		>
			<CalendarIcon class="size-4" />
			{selected ? df.format(selected.toDate(getLocalTimeZone())) : "View as of…"}
		</Popover.Trigger>
		<Popover.Content class="w-auto p-0" align="start">
			<Calendar
				type="single"
				value={selected}
				maxValue={today(getLocalTimeZone())}
				onValueChange={(v) => {
					if (v) {
						apply(v.toString());
						open = false;
					}
				}}
			/>
		</Popover.Content>
	</Popover.Root>
	{#if value}
		<Button variant="ghost" size="icon" title="Back to current" onclick={() => apply("")}>
			<XIcon class="size-4" />
		</Button>
	{/if}
</div>
