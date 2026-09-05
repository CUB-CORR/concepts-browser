<script lang="ts">
	import * as DropdownMenu from "$lib/components/ui/dropdown-menu";
	import { Button, buttonVariants } from "$lib/components/ui/button";
	import { enhance } from "$app/forms";
	import { cn } from "$lib/utils";
	import UserIcon from "@lucide/svelte/icons/user";
	import IdCardIcon from "@lucide/svelte/icons/id-card";
	import KeyRoundIcon from "@lucide/svelte/icons/key-round";
	import LogOutIcon from "@lucide/svelte/icons/log-out";
	import LogInIcon from "@lucide/svelte/icons/log-in";
	import { can } from "$lib/caps";
	import type { User } from "$lib/types";

	let { user }: { user: User | null } = $props();
</script>

{#if user}
	<DropdownMenu.Root>
		<DropdownMenu.Trigger class={cn(buttonVariants({ variant: "outline", size: "sm" }))}>
			<UserIcon class="size-4" />
			{user.display_name ?? user.username}
		</DropdownMenu.Trigger>
		<DropdownMenu.Content align="end" class="w-60">
			<DropdownMenu.Label>
				<div class="flex flex-col gap-0.5">
					<span>{user.display_name ?? user.username}</span>
					<span class="text-muted-foreground text-xs font-normal">
						{user.capabilities.length ? user.capabilities.join(", ") : "no capabilities"}
					</span>
				</div>
			</DropdownMenu.Label>
			<DropdownMenu.Separator />
			<DropdownMenu.Item>
				{#snippet child({ props })}
					<a href="/users/{encodeURIComponent(user.username)}/profile" {...props}>
						<IdCardIcon class="size-4" />
						Profile
					</a>
				{/snippet}
			</DropdownMenu.Item>
			{#if can(user, "create_api_key")}
				<DropdownMenu.Item>
					{#snippet child({ props })}
						<a href="/api-keys" {...props}>
							<KeyRoundIcon class="size-4" />
							API keys
						</a>
					{/snippet}
				</DropdownMenu.Item>
			{/if}
			<DropdownMenu.Separator />
			<form method="POST" action="/login?/logout" use:enhance>
				<button
					type="submit"
					class="hover:bg-accent flex w-full cursor-default items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none"
				>
					<LogOutIcon class="size-4" />
					Sign out
				</button>
			</form>
		</DropdownMenu.Content>
	</DropdownMenu.Root>
{:else}
	<Button href="/login" variant="default" size="sm">
		<LogInIcon class="size-4" />
		Sign in
	</Button>
{/if}
