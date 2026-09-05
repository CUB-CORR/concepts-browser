<script lang="ts">
	import UserMenu from "./UserMenu.svelte";
	import * as DropdownMenu from "$lib/components/ui/dropdown-menu";
	import { Button } from "$lib/components/ui/button";
	import { Separator } from "$lib/components/ui/separator";
	import { Badge } from "$lib/components/ui/badge";
	import SunIcon from "@lucide/svelte/icons/sun";
	import MoonIcon from "@lucide/svelte/icons/moon";
	import ChevronDownIcon from "@lucide/svelte/icons/chevron-down";
	import ExternalLinkIcon from "@lucide/svelte/icons/external-link";
	import { mode, toggleMode } from "mode-watcher";
	import { page } from "$app/state";
	import { withDate, cn } from "$lib/utils";
	import { can } from "$lib/caps";
	import { brand } from "$lib/brand";
	import type { PendingCounts, User } from "$lib/types";

	let {
		user,
		date,
		counts = null,
	}: { user: User | null; date: string; counts?: PendingCounts | null } = $props();

	// Primary navigation. Concepts is the default landing route (and what the logo links to);
	// the menu holds the concept list and the source file libraries — files belong to the
	// concepts area, not beside it, since they exist only to be read by a definition.
	const conceptsNav = [
		{ label: "All concepts", href: "/concepts" },
		{ label: "Data files", href: "/files" },
	];

	const nav = [{ label: "Projects", href: "/projects" }];

	// User management and the audit log are admin-only, set apart behind a separator.
	const adminNav = [
		{ label: "Users", href: "/users" },
		{ label: "Audit", href: "/audit" },
	];

	// Documentation links. The in-app user guide comes first — it is the one that explains this
	// app rather than a library or an endpoint list — and stays in the tab, so it is the only
	// entry here that is not external. The API docs URL is deployment config (see $lib/brand).
	const docs = [
		{ label: "User guide", href: "/docs", external: false },
		{ label: "CORR-Vars", href: "https://github.com/CUB-CORR/corr-vars", external: true },
		...(brand.apiDocsUrl ? [{ label: "API", href: brand.apiDocsUrl, external: true }] : []),
	];

	function isActive(href: string): boolean {
		return page.url.pathname === href || page.url.pathname.startsWith(href + "/");
	}
</script>

<header class="bg-background sticky top-0 z-40 border-b">
	<div class="flex h-14 items-center gap-4 px-4">
		<!-- The product name is deployment config and can be a full institute's name, so it is
		     never allowed to wrap: below `lg` the logo mark stands for it alone, and above it the
		     name is laid out on one line beside the navigation rather than squeezed into it. -->
		<a
			href={withDate("/concepts", date)}
			class="flex shrink-0 items-center gap-2.5"
			aria-label={brand.appName}
		>
			<img src={brand.logoLight} alt="" class="h-8 w-auto dark:hidden" />
			<img src={brand.logoDark} alt="" class="hidden h-8 w-auto dark:block" />
			<span class="font-heading hidden font-normal whitespace-nowrap lg:inline">
				{brand.appName}
			</span>
		</a>
		{#if user}
			<nav class="flex items-center gap-1">
				<!-- The label navigates; only the chevron opens the menu. -->
				<div
					class={cn(
						"flex items-center rounded-md text-sm font-medium transition-colors",
						isActive("/concepts") || isActive("/files")
							? "bg-accent text-accent-foreground"
							: "text-muted-foreground hover:text-foreground hover:bg-accent/50",
					)}
				>
					<a href={withDate("/concepts", date)} class="py-1.5 pr-1 pl-3">Concepts</a>
					<DropdownMenu.Root>
						<DropdownMenu.Trigger
							class="rounded-md py-1.5 pr-2 pl-1 outline-none"
							aria-label="Open concepts menu"
						>
							<ChevronDownIcon class="size-3.5" />
						</DropdownMenu.Trigger>
						<DropdownMenu.Content align="start" class="w-44">
							{#each conceptsNav as item (item.href)}
								<DropdownMenu.Item>
									{#snippet child({ props })}
										<a href={withDate(item.href, date)} {...props}>{item.label}</a>
									{/snippet}
								</DropdownMenu.Item>
							{/each}
						</DropdownMenu.Content>
					</DropdownMenu.Root>
				</div>
				{#each nav as item (item.href)}
					{@render navLink(item)}
				{/each}
				<DropdownMenu.Root>
					<DropdownMenu.Trigger
						class={cn(
							"flex items-center gap-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors outline-none",
							isActive("/docs")
								? "bg-accent text-accent-foreground"
								: "text-muted-foreground hover:text-foreground hover:bg-accent/50",
						)}
					>
						Docs
						<ChevronDownIcon class="size-3.5" />
					</DropdownMenu.Trigger>
					<DropdownMenu.Content align="start" class="w-44">
						{#each docs as doc (doc.href)}
							<DropdownMenu.Item>
								{#snippet child({ props })}
									{#if doc.external}
										<a href={doc.href} target="_blank" rel="noopener noreferrer" {...props}>
											{doc.label}
											<ExternalLinkIcon class="ml-auto size-3.5 opacity-60" />
										</a>
									{:else}
										<a href={withDate(doc.href, date)} {...props}>{doc.label}</a>
									{/if}
								{/snippet}
							</DropdownMenu.Item>
						{/each}
					</DropdownMenu.Content>
				</DropdownMenu.Root>
				{#if can(user, "can_publish")}
					<!-- The review queues are reviewers' work, not admins', and reviewing *is*
					     `can_publish`: whoever watches the queue is who answers it. -->
					{@render navLink({ label: "Review", href: "/review", count: counts?.review })}
				{/if}
				{#if can(user, "can_admin")}
					<Separator orientation="vertical" class="mx-2 data-[orientation=vertical]:h-5" />
					{#each adminNav as item (item.href)}
						{@render navLink({
							...item,
							count: item.href === "/users" ? counts?.pending_users : null,
						})}
					{/each}
				{/if}
			</nav>
		{/if}
		<div class="ml-auto flex items-center gap-2">
			<Button
				variant="ghost"
				size="icon"
				title="Toggle theme"
				aria-label="Toggle theme"
				onclick={toggleMode}
			>
				{#if mode.current === "dark"}
					<MoonIcon class="size-4" />
				{:else}
					<SunIcon class="size-4" />
				{/if}
			</Button>
			<UserMenu {user} />
		</div>
	</div>
</header>

{#snippet navLink(item: { label: string; href: string; count?: number | null })}
	<a
		href={withDate(item.href, date)}
		aria-current={isActive(item.href) ? "page" : undefined}
		class={cn(
			"flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
			isActive(item.href)
				? "bg-accent text-accent-foreground"
				: "text-muted-foreground hover:text-foreground hover:bg-accent/50",
		)}
	>
		{item.label}
		<!-- Nothing waiting is not news: the badge exists only when there is a number above zero
		     to show, so an empty queue reads as a plain nav item. -->
		{#if item.count}
			<Badge class="h-4 min-w-4 px-1 text-[10px] tabular-nums" aria-label="{item.count} waiting">
				{item.count}
			</Badge>
		{/if}
	</a>
{/snippet}
