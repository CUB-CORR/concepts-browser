<script lang="ts">
	import { enhance } from "$app/forms";
	import * as Card from "$lib/components/ui/card";
	import * as Alert from "$lib/components/ui/alert";
	import { Button } from "$lib/components/ui/button";
	import { Input } from "$lib/components/ui/input";
	import { Label } from "$lib/components/ui/label";
	import LogInIcon from "@lucide/svelte/icons/log-in";
	import TriangleAlertIcon from "@lucide/svelte/icons/triangle-alert";
	import LoaderIcon from "@lucide/svelte/icons/loader-circle";
	import { brand } from "$lib/brand";
	import type { ActionData, PageData } from "./$types";

	let { form, data }: { form: ActionData; data: PageData } = $props();
	let submitting = $state(false);
</script>

<svelte:head><title>Sign in · Concepts</title></svelte:head>

<div
	class="flex min-h-screen flex-col items-center justify-center overflow-hidden bg-cover bg-center bg-no-repeat px-4 md:items-center md:pl-[60%]"
	style="background-image: url('{brand.loginBackground}');"
>
	<Card.Root class="w-full max-w-sm">
		<Card.Header>
			<img src={brand.logoLight} alt="" class="mx-auto mb-2 w-40 max-w-full dark:hidden" />
			<img src={brand.logoDark} alt="" class="mx-auto mb-2 hidden w-40 max-w-full dark:block" />
			<Card.Title>Sign in</Card.Title>
			<Card.Description>{brand.loginHint}</Card.Description>
		</Card.Header>
		<form
			method="POST"
			action="?/login"
			use:enhance={() => {
				submitting = true;
				return async ({ update }) => {
					await update();
					submitting = false;
				};
			}}
		>
			<Card.Content class="flex flex-col gap-4">
				{#if form?.error}
					<Alert.Root variant="destructive">
						<TriangleAlertIcon class="size-4" />
						<Alert.Description>{form.error}</Alert.Description>
					</Alert.Root>
				{/if}
				<input type="hidden" name="redirectTo" value={data.redirectTo} />
				<div class="flex flex-col gap-1.5">
					<Label for="username">Username</Label>
					<Input id="username" name="username" autocomplete="username" required
						value={form?.username ?? ""} />
				</div>
				<div class="flex flex-col gap-1.5">
					<Label for="password">Password</Label>
					<Input id="password" name="password" type="password" autocomplete="current-password" required />
				</div>
			</Card.Content>
			<Card.Footer class="mt-2">
				<Button type="submit" class="w-full" disabled={submitting}>
					{#if submitting}<LoaderIcon class="size-4 animate-spin" />{:else}<LogInIcon class="size-4" />{/if}
					Sign in
				</Button>
			</Card.Footer>
		</form>
	</Card.Root>
</div>
