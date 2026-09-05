<script lang="ts">
	import { Badge } from "$lib/components/ui/badge";
	import ArrowLeftIcon from "@lucide/svelte/icons/arrow-left";
	import UserIcon from "@lucide/svelte/icons/user";
	import MailIcon from "@lucide/svelte/icons/mail";
	import ChevronRightIcon from "@lucide/svelte/icons/chevron-right";
	import UsageTable from "$lib/components/UsageTable.svelte";
	import { CAPABILITY_CHAIN, can, hasCapability } from "$lib/caps";
	import { brand } from "$lib/brand";
	import { formatTimestamp } from "$lib/format";
	import type { Capability } from "$lib/types";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();

	const CAP_LABELS: Record<Capability, string> = {
		can_read: "Read",
		can_read_detail: "Read code",
		can_edit: "Edit",
		can_publish: "Publish",
		create_api_key: "API keys",
		add_project: "Add projects",
		can_admin: "Admin",
	};

	const profile = $derived(data.profile);
	// Primary email from the directory snapshot (standard `mail` attribute), when present.
	const email = $derived(profile.ldap_profile?.mail?.[0] ?? null);
	// Directory attributes as sorted [name, values] pairs (empty when a local account).
	const ldapEntries = $derived(
		Object.entries(profile.ldap_profile ?? {}).sort(([a], [b]) =>
			a.toLowerCase().localeCompare(b.toLowerCase()),
		),
	);
	// An admin viewing this page can jump back to the user list.
	const showBackLink = $derived(!data.isSelf && can(data.user, "can_admin"));

	// Granted rows are what an admin ticked; the chain hands out the rest (see `$lib/caps`),
	// and a profile that showed only the stored half would understate what the account can do.
	const implied = $derived(
		CAPABILITY_CHAIN.filter(
			(c) => !profile.capabilities.includes(c) && hasCapability(profile.capabilities, c),
		),
	);

	// The raw directory dump is collapsed by default; the viewer expands it on demand.
	let showDirectory = $state(false);

	const usage = $derived(data.usage);
</script>

<svelte:head><title>{profile.display_name ?? profile.username} · Profile</title></svelte:head>

<div class="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-6">
	{#if showBackLink}
		<a
			href="/users"
			class="text-muted-foreground hover:text-foreground flex w-fit items-center gap-1 text-sm"
		>
			<ArrowLeftIcon class="size-4" /> User management
		</a>
	{/if}

	<div class="flex items-start gap-4">
		<div class="bg-muted flex size-14 shrink-0 items-center justify-center rounded-full">
			<UserIcon class="text-muted-foreground size-7" />
		</div>
		<div class="flex min-w-0 flex-col gap-1">
			<h1 class="text-2xl font-semibold tracking-tight">
				{profile.display_name ?? profile.username}
			</h1>
			<div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
				<span class="text-muted-foreground">{profile.username}</span>
				{#if email}
					<a
						href="mailto:{email}"
						class="text-primary inline-flex min-w-0 items-center gap-1 hover:underline"
					>
						<MailIcon class="size-3.5 shrink-0" />
						<span class="truncate">{email}</span>
					</a>
				{/if}
			</div>
			<div class="mt-1 flex flex-wrap items-center gap-2">
				<Badge variant={profile.is_ldap ? "secondary" : "outline"}>
					{profile.is_ldap ? "LDAP account" : "Local account"}
				</Badge>
				<Badge variant={profile.is_active ? "secondary" : "destructive"}>
					{profile.is_active ? "Active" : "Disabled"}
				</Badge>
			</div>
		</div>
	</div>

	<!-- Capabilities -->
	<section class="flex flex-col gap-2">
		<h2 class="text-sm font-semibold tracking-tight">Capabilities</h2>
		{#if profile.capabilities.length}
			<div class="flex flex-wrap gap-2">
				{#each profile.capabilities as cap (cap)}
					<Badge variant="secondary">{CAP_LABELS[cap] ?? cap}</Badge>
				{/each}
			</div>
			{#if profile.capabilities.includes("can_admin")}
				<p class="text-muted-foreground text-xs">Admin implies every other capability.</p>
			{:else if implied.length}
				<p class="text-muted-foreground text-xs">
					Also held, implied by the above: {implied.map((c) => CAP_LABELS[c] ?? c).join(", ")}.
				</p>
			{/if}
		{:else}
			<p class="text-muted-foreground text-sm">
				No capabilities yet — this account is pending admin approval.
			</p>
		{/if}
	</section>

	<!-- API usage, from the audit log (see api/usage.py) -->
	{#if usage}
		<section class="flex flex-col gap-3">
			<h2 class="text-sm font-semibold tracking-tight">API usage</h2>
			<div class="grid grid-cols-2 gap-3 sm:grid-cols-3">
				<div class="rounded-lg border px-4 py-3">
					<div class="text-muted-foreground text-xs">Last active</div>
					<div class="mt-0.5 text-sm font-medium">
						{usage.last_active_at ? formatTimestamp(usage.last_active_at) : "never"}
					</div>
				</div>
				<div class="rounded-lg border px-4 py-3">
					<div class="text-muted-foreground text-xs">Concepts used</div>
					<div class="mt-0.5 text-sm font-medium">{usage.concepts_used}</div>
				</div>
				<div class="rounded-lg border px-4 py-3">
					<div class="text-muted-foreground text-xs">Concept reads</div>
					<div class="mt-0.5 text-sm font-medium">{usage.total_reads}</div>
				</div>
			</div>

			{#if usage.concepts.length}
				<UsageTable concepts={usage.concepts} />
			{:else}
				<p class="text-muted-foreground text-sm">
					{data.isSelf ? "You have" : "This user has"} not read any concept yet.
				</p>
			{/if}
		</section>
	{/if}

	<!-- LDAP directory profile -->
	<section class="flex flex-col gap-2">
		{#if ldapEntries.length}
			<div class="flex items-center justify-between gap-4">
				<button
					type="button"
					onclick={() => (showDirectory = !showDirectory)}
					aria-expanded={showDirectory}
					class="text-foreground -ml-1 flex items-center gap-1.5 rounded-md p-1 text-sm font-semibold tracking-tight hover:underline"
				>
					<ChevronRightIcon
						class={"text-muted-foreground size-4 transition-transform " +
							(showDirectory ? "rotate-90" : "")}
					/>
					Directory profile
					<span class="text-muted-foreground ml-0.5 text-xs font-normal">
						{ldapEntries.length}
						{ldapEntries.length === 1 ? "attribute" : "attributes"}
					</span>
				</button>
				{#if profile.is_ldap && brand.directoryLogoLight}
					<!-- Directory brand mark: separate variant for dark mode. -->
					<img src={brand.directoryLogoLight} alt="" class="h-6 w-auto dark:hidden" />
					<img src={brand.directoryLogoDark} alt="" class="hidden h-6 w-auto dark:block" />
				{/if}
			</div>
			{#if showDirectory}
				<div class="overflow-hidden rounded-lg border">
					<dl class="divide-y text-sm">
						{#each ldapEntries as [name, values] (name)}
							<div class="grid grid-cols-1 gap-1 px-4 py-2.5 sm:grid-cols-[minmax(0,12rem)_1fr] sm:gap-4">
								<dt class="text-muted-foreground font-mono text-xs break-all sm:pt-0.5">
									{name}
								</dt>
								<dd class="flex min-w-0 flex-col gap-0.5">
									{#each values as value, i (i)}
										<span class="break-all">{value}</span>
									{/each}
								</dd>
							</div>
						{/each}
					</dl>
				</div>
			{/if}
		{:else}
			<h2 class="text-sm font-semibold tracking-tight">Directory profile</h2>
			<p class="text-muted-foreground text-sm">
				No directory profile — this is a local account with no LDAP entry.
			</p>
		{/if}
	</section>
</div>
