<script lang="ts">
	import type { ActivityWindow } from "$lib/types";

	// A single-series magnitude-over-time bar chart (one accent hue, recessive axis, per-bar
	// hover). `bucket` picks the tick-label format; the series is named by the caller's title.
	let { window, bucket }: { window: ActivityWindow; bucket: "hour" | "day" } = $props();

	const max = $derived(Math.max(1, ...window.buckets.map((b) => b.count)));

	function tick(iso: string): string {
		const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
		if (isNaN(d.getTime())) return "";
		return bucket === "hour"
			? new Intl.DateTimeFormat("en-GB", { hour: "2-digit", hourCycle: "h23", timeZone: "UTC" }).format(d)
			: new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "2-digit", timeZone: "UTC" }).format(d);
	}

	function full(iso: string): string {
		const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
		return isNaN(d.getTime())
			? iso
			: new Intl.DateTimeFormat("en-GB", {
					day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
					hourCycle: "h23", timeZone: "UTC",
				}).format(d) + " UTC";
	}

	// Show at most ~8 axis ticks so labels never collide.
	const tickEvery = $derived(Math.max(1, Math.ceil(window.buckets.length / 8)));
</script>

{#if window.total === 0}
	<div class="text-muted-foreground flex h-32 items-center justify-center rounded-md border border-dashed text-sm">
		No requests in this window.
	</div>
{:else}
	<div class="flex h-32 items-end gap-[2px] border-b pb-px" role="img" aria-label="Requests over time">
		{#each window.buckets as b, i (i)}
			<div
				class="group relative flex-1"
				style="height: 100%"
				title={`${full(b.ts)} — ${b.count} request${b.count === 1 ? "" : "s"}`}
			>
				<div
					class="bg-primary/80 group-hover:bg-primary absolute bottom-0 w-full rounded-t-[3px] transition-colors"
					style={`height: ${(b.count / max) * 100}%`}
				></div>
			</div>
		{/each}
	</div>
	<div class="text-muted-foreground mt-1 flex justify-between text-[10px]">
		{#each window.buckets as b, i (i)}
			{#if i % tickEvery === 0}
				<span class="flex-1 text-left">{tick(b.ts)}</span>
			{/if}
		{/each}
	</div>
{/if}
