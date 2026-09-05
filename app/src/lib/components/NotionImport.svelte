<script lang="ts">
	import { Input } from "$lib/components/ui/input";
	import { Label } from "$lib/components/ui/label";
	import { Button } from "$lib/components/ui/button";
	import * as Alert from "$lib/components/ui/alert";
	import InfoIcon from "@lucide/svelte/icons/info";
</script>

<!-- Placeholder: importing a concept straight from a Notion page is not wired up yet. -->
<div class="flex flex-col gap-4">
	<Alert.Root>
		<InfoIcon class="size-4" />
		<Alert.Title>Coming soon</Alert.Title>
		<Alert.Description>
			Importing a concept from a Notion page isn't wired up yet. For now, create it manually.
		</Alert.Description>
	</Alert.Root>
	<div class="flex flex-col gap-1.5 opacity-60">
		<Label for="notion-url">Notion page URL</Label>
		<Input id="notion-url" placeholder="https://www.notion.so/…" disabled />
	</div>
	<Button disabled class="w-fit">Import</Button>
</div>
