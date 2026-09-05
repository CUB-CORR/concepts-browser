<script lang="ts">
	import { enhance } from "$app/forms";
	import * as Card from "$lib/components/ui/card";
	import { Button } from "$lib/components/ui/button";
	import { Label } from "$lib/components/ui/label";
	import { Textarea } from "$lib/components/ui/textarea";
	import TargetIcon from "@lucide/svelte/icons/target";
	import LoaderCircleIcon from "@lucide/svelte/icons/loader-circle";
	import PencilIcon from "@lucide/svelte/icons/pencil";
	import type { Project } from "$lib/types";

	let { project, canEdit }: { project: Project; canEdit: boolean } = $props();

	let editing = $state(false);
	let saving = $state(false);
	let errorMsg = $state<string | null>(null);

	// The four PICO elements in their canonical order, each paired with the form field name the
	// server action reads (see `saveStudyContext`).
	const PICO = [
		{ key: "population", label: "Population", hint: "Who the study is about" },
		{ key: "intervention", label: "Intervention", hint: "What is done or measured" },
		{ key: "comparison", label: "Comparison", hint: "What it is contrasted with" },
		{ key: "outcome", label: "Outcome", hint: "What is observed" },
	] as const;

	const pico = $derived(
		PICO.map((el) => ({ ...el, value: project[`pico_${el.key}` as const] })),
	);
	const hasPico = $derived(pico.some((el) => el.value));
	const hasContent = $derived(hasPico || Boolean(project.study_team));
</script>

<!-- The PICO frame and the study team behind the project — the study it is, as opposed to any
     concept it reads. Edited through the project PATCH, so the gate is the project's own:
     a lead or an admin. Nothing else writes these fields, so the card stays hidden entirely
     until someone who may edit it fills it in. -->
{#if hasContent || canEdit}
	<Card.Root class="bg-muted/40">
		<Card.Header>
			<Card.Title class="text-muted-foreground flex items-center gap-2 text-sm font-medium">
				<TargetIcon class="size-4" /> Study context
				{#if canEdit && !editing}
					<span class="ml-auto">
						<Button
							variant="ghost"
							size="icon"
							class="size-6"
							title="Edit study context"
							aria-label="Edit study context"
							onclick={() => {
								errorMsg = null;
								editing = true;
							}}
						>
							<PencilIcon class="size-3.5" />
						</Button>
					</span>
				{/if}
			</Card.Title>
		</Card.Header>
		<Card.Content class="text-sm">
			{#if editing}
				<form
					method="POST"
					action="?/saveStudyContext"
					class="flex flex-col gap-3"
					use:enhance={() => {
						saving = true;
						errorMsg = null;
						return async ({ result, update }) => {
							saving = false;
							if (result.type === "failure") {
								errorMsg = (result.data as { error?: string })?.error ?? "Saving failed.";
							} else {
								editing = false;
							}
							await update({ reset: false });
						};
					}}
				>
					<span class="text-muted-foreground text-xs font-medium">PICO</span>
					{#each pico as el (el.key)}
						<div class="flex flex-col gap-1.5">
							<Label for="pico-{el.key}">{el.label}</Label>
							<Textarea id="pico-{el.key}" name={el.key} rows={2} value={el.value ?? ""} />
						</div>
					{/each}
					<div class="flex flex-col gap-1.5">
						<Label for="study-team">Study team <span class="text-muted-foreground font-normal">(Projektteilnehmer)</span></Label>
						<Textarea id="study-team" name="team" rows={3} value={project.study_team ?? ""} />
					</div>
					{#if errorMsg}
						<p class="text-destructive text-xs">{errorMsg}</p>
					{/if}
					<div class="flex items-center gap-2">
						<Button type="submit" size="sm" disabled={saving}>
							{#if saving}<LoaderCircleIcon class="size-3.5 animate-spin" />{/if}
							Save
						</Button>
						<Button
							type="button"
							variant="ghost"
							size="sm"
							disabled={saving}
							onclick={() => (editing = false)}
						>
							Cancel
						</Button>
					</div>
				</form>
			{:else}
				<div class="flex flex-col gap-3">
					{#if hasPico}
						<div class="flex flex-col gap-1.5">
							<span class="text-muted-foreground text-xs font-medium">PICO</span>
							<dl class="flex flex-col gap-1.5">
								{#each pico as el (el.key)}
									{#if el.value}
										<div class="grid grid-cols-[5.5rem_1fr] gap-2">
											<dt class="text-muted-foreground text-xs" title={el.hint}>{el.label}</dt>
											<dd class="min-w-0 whitespace-pre-line text-sm">{el.value}</dd>
										</div>
									{/if}
								{/each}
							</dl>
						</div>
					{/if}

					{#if project.study_team}
						<div class="flex flex-col gap-0.5">
							<span class="text-muted-foreground text-xs font-medium">
								Study team <span class="font-normal">(Projektteilnehmer)</span>
							</span>
							<p class="whitespace-pre-line">{project.study_team}</p>
						</div>
					{/if}

					{#if !hasContent}
						<p class="text-muted-foreground text-xs">
							No study context yet. Use the pencil to add the PICO frame and the study team.
						</p>
					{/if}
				</div>
			{/if}
		</Card.Content>
	</Card.Root>
{/if}
