<script lang="ts">
	import { enhance } from "$app/forms";
	import * as Card from "$lib/components/ui/card";
	import { Button } from "$lib/components/ui/button";
	import ClockIcon from "@lucide/svelte/icons/clock";
	import LogOutIcon from "@lucide/svelte/icons/log-out";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();
</script>

<svelte:head><title>Approval pending</title></svelte:head>

<div class="mx-auto flex max-w-md flex-col gap-6 px-4 py-16">
	<Card.Root>
		<Card.Header class="items-center text-center">
			<div
				class="mb-2 flex size-12 items-center justify-center rounded-full bg-amber-100 text-amber-700 dark:bg-amber-950/50 dark:text-amber-400"
			>
				<ClockIcon class="size-6" />
			</div>
			<Card.Title class="text-xl">Approval pending</Card.Title>
			<Card.Description>
				Your account has been created and is pending review by an administrator.
			</Card.Description>
		</Card.Header>
		<Card.Content class="text-muted-foreground text-center text-sm">
			<p>
				You're signed in as
				<span class="text-foreground font-medium">{data.user.display_name ?? data.user.username}</span>.
				Once an administrator grants you access, you'll be able to browse concepts. You may need
				to sign in again after approval.
			</p>
		</Card.Content>
		<Card.Footer class="justify-center">
			<form method="POST" action="/login?/logout" use:enhance>
				<Button type="submit" variant="outline" size="sm">
					<LogOutIcon class="size-4" />
					Sign out
				</Button>
			</form>
		</Card.Footer>
	</Card.Root>
</div>
