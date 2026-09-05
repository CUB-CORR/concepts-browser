<script lang="ts">
	import "./layout.css";
	import { ModeWatcher } from "mode-watcher";
	import { Toaster } from "$lib/components/ui/sonner";
	import * as Tooltip from "$lib/components/ui/tooltip";
	import TopBar from "$lib/components/TopBar.svelte";
	import { appConfig } from "$lib/config";
	import { brand } from "$lib/brand";
	import { goto } from "$app/navigation";
	import { page } from "$app/state";
	import HistoryIcon from "@lucide/svelte/icons/history";
	import TriangleAlertIcon from "@lucide/svelte/icons/triangle-alert";

	let { children, data } = $props();

	const banner = appConfig.banner;

	function resetDate() {
		const url = new URL(page.url);
		url.searchParams.delete("date");
		url.searchParams.delete("d");
		goto(url, { invalidateAll: true });
	}
</script>

<ModeWatcher />
<Toaster richColors closeButton />

<Tooltip.Provider delayDuration={200}>
<div class="flex min-h-screen flex-col">
	{#if banner.enabled && data.user}
		<div
			class="flex items-center gap-2 border-b border-neutral-200 bg-neutral-100 px-4 py-2 text-sm text-neutral-700 dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-300"
		>
			<TriangleAlertIcon class="size-4 shrink-0" />
			<span>
				{banner.message}
				{#if banner.linkHref && banner.linkLabel}
					<a
						href={banner.linkHref}
						target="_blank"
						rel="noopener noreferrer"
						class="font-medium underline underline-offset-2"
					>
						{banner.linkLabel}
					</a>
				{/if}
			</span>
		</div>
	{/if}

	{#if data.user}
		<TopBar user={data.user} date={data.date} counts={data.counts} />
	{/if}

	{#if data.date}
		<div
			class="flex items-center gap-2 border-b border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-200"
		>
			<HistoryIcon class="size-4" />
			<span>
				Viewing historical state <strong>as of {data.date}</strong> — versions, sources and configs
				reflect that date.
			</span>
			<button class="ml-auto font-medium underline underline-offset-2" onclick={resetDate}>
				Back to current
			</button>
		</div>
	{/if}

	<main class="flex-1">
		{@render children()}
	</main>

	{#if brand.footerText || brand.buildCommit}
		<footer
			class="text-muted-foreground flex items-center justify-center gap-3 border-t px-4 py-3 text-xs"
		>
			{#if brand.footerText}
				<a
					href={brand.footerUrl || undefined}
					target="_blank"
					rel="noopener noreferrer"
					class="flex items-center justify-center gap-2 hover:underline"
				>
					<span>{brand.footerText}</span>
					{#if brand.footerLogoLight}
						<img src={brand.footerLogoLight} alt="" class="h-5 w-auto dark:hidden" />
						<img src={brand.footerLogoDark} alt="" class="hidden h-5 w-auto dark:block" />
					{/if}
				</a>
			{/if}
			{#if brand.buildCommit}
				<!-- Which release is live: short hash, full hash on hover. -->
				<span class="font-mono opacity-60" title={brand.buildCommit}>
					{brand.buildCommit.slice(0, 7)}
				</span>
			{/if}
		</footer>
	{/if}
</div>

</Tooltip.Provider>
