<script lang="ts">
	import * as Dialog from "$lib/components/ui/dialog";
	import { Badge } from "$lib/components/ui/badge";
	import CodeBlock from "$lib/components/CodeBlock.svelte";
	import type { AuditEvent } from "$lib/types";

	// `event` is null when nothing is selected; the dialog is open exactly when one is.
	let { event = $bindable() }: { event: AuditEvent | null } = $props();

	const open = $derived(event !== null);

	// The concept selector is what the client *asked for*; `concept_version` is what it got.
	// Spelling both out is the point of this view — they differ whenever a client pins a
	// version or reads as-of a past date.
	const selector = $derived(event?.detail?.selector ?? null);
	const askedFor = $derived.by(() => {
		if (!selector) return null;
		if (selector.v !== null) return `version ${selector.v}`;
		if (selector.date !== null) return `as of ${selector.date}`;
		if (selector.draft !== null) return `draft #${selector.draft}`;
		return "current version";
	});

	const isEmail = $derived(event?.event === "email");

	// Why a message never left. The wording an admin needs is "what do I do about it", so a
	// missing directory address (nothing to do — the person is unreachable) reads differently
	// from mail being switched off (turn it on) or the server refusing us (fix the config).
	const REASONS: Record<string, string> = {
		no_ldap_mail_address: "the directory has no email address for this user",
		mail_disabled: "email is switched off on this server (EXCHANGE_ENABLED=false)",
		no_exchange_password: "email is switched on but EXCHANGE_PASSWORD is unset",
	};

	const rows = $derived.by(() => {
		if (!event) return [];

		if (isEmail) {
			const reason = event.detail?.reason;
			const r: { label: string; value: string }[] = [
				{ label: "When", value: new Date(event.created_at + "Z").toLocaleString() },
				{ label: "Event", value: "Email" },
				{
					label: "Recipient",
					value: event.user?.display_name || event.user?.username || "—",
				},
				{ label: "Address", value: event.email_to ?? "none in the directory" },
				{ label: "Subject", value: event.email_subject ?? "—" },
				{ label: "Message", value: event.email_kind ?? "—" },
				{ label: "Status", value: event.email_status ?? "—" },
			];
			if (reason) {
				r.push({ label: "Reason", value: REASONS[reason] ?? reason });
			}
			// An approval email's one non-boilerplate claim: what it told them they can now do.
			if (event.detail?.capabilities?.length) {
				r.push({ label: "Granted", value: event.detail.capabilities.join(", ") });
			}
			return r;
		}

		const r: { label: string; value: string }[] = [
			{ label: "When", value: new Date(event.created_at + "Z").toLocaleString() },
			{ label: "Event", value: event.event === "login" ? "Login" : "API call" },
			{
				label: "User",
				value:
					event.user?.display_name ||
					event.user?.username ||
					// A failed login authenticates nobody; the attempted name is all we have.
					(event.detail?.username ? `${event.detail.username} (not authenticated)` : "—"),
			},
			{ label: "Endpoint", value: `${event.method} ${event.path}` },
			{ label: "Status", value: String(event.status_code ?? "—") },
			{ label: "Client", value: event.client_type === "app" ? "Web app" : "External client" },
			{ label: "Auth", value: event.auth_method ?? "—" },
			{ label: "Project", value: event.project_name ?? "—" },
			{ label: "IP address", value: event.ip_address ?? "—" },
			{ label: "User agent", value: event.user_agent ?? "—" },
		];
		if (event.concept_name) {
			r.splice(7, 0, { label: "Concept", value: `${event.concept_name} (${event.taxonomy})` });
			r.splice(8, 0, {
				label: "Version served",
				value: event.concept_version !== null ? `v${event.concept_version}` : "none published",
			});
			if (askedFor) r.splice(9, 0, { label: "Requested", value: askedFor });
		}
		return r;
	});

	const raw = $derived(
		event
			? JSON.stringify(
					{
						method: event.method,
						path: event.path,
						query_string: event.query_string,
						...event.detail,
					},
					null,
					2,
				)
			: "",
	);
</script>

<Dialog.Root
	{open}
	onOpenChange={(next) => {
		if (!next) event = null;
	}}
>
	<Dialog.Content class="sm:max-w-2xl">
		<Dialog.Header>
			<Dialog.Title class="flex items-center gap-2">
				Request detail
				{#if event}
					<Badge variant={event.status_code && event.status_code < 400 ? "outline" : "destructive"}>
						{event.status_code}
					</Badge>
				{/if}
			</Dialog.Title>
			<Dialog.Description>
				The full request as it was received, exactly as recorded in the audit log.
			</Dialog.Description>
		</Dialog.Header>

		{#if event}
			<dl class="grid grid-cols-[9rem_1fr] gap-x-4 gap-y-2 text-sm">
				{#each rows as row (row.label)}
					<dt class="text-muted-foreground">{row.label}</dt>
					<dd class="break-all">{row.value}</dd>
				{/each}
			</dl>

			<div class="flex flex-col gap-1.5">
				<span class="text-muted-foreground text-xs font-medium">Full request</span>
				<CodeBlock code={raw} language="json" />
			</div>
		{/if}
	</Dialog.Content>
</Dialog.Root>
