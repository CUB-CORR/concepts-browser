<script lang="ts">
	import DocPage from "$lib/components/docs/DocPage.svelte";
	import DocSection from "$lib/components/docs/DocSection.svelte";
	import AppLink from "$lib/components/docs/AppLink.svelte";
	import * as Table from "$lib/components/ui/table";
	import * as Alert from "$lib/components/ui/alert";
	import HistoryIcon from "@lucide/svelte/icons/history";
</script>

<DocPage slug="search">
	<DocSection id="finding" title="Finding a concept">
		<p>There are three ways in, and they answer different questions:</p>
		<ul class="ml-4 flex list-disc flex-col gap-1.5">
			<li>
				<strong>The search box on <AppLink href="/concepts">the concept list</AppLink></strong> filters
				what is already loaded, by name, label and description, within the active taxonomy. Fast, and
				the right tool when you roughly know what you are looking for.
			</li>
			<li>
				<strong>The concept picker</strong> — used wherever you have to point at another concept
				(adding a name to an existing concept, naming a successor when requesting a deprecation) —
				searches the whole repository across <em>every</em> taxonomy as you type, and shows each hit
				with all of its matching names, so you can tell two similarly named concepts apart before
				choosing one.
			</li>
			<li>
				<strong>The URL</strong>, when you already know the identity. See
				<a href="#links" class="text-primary underline-offset-4 hover:underline">stable links</a> below.
			</li>
		</ul>
	</DocSection>

	<DocSection id="taxonomy" title="The taxonomy selector">
		<p>
			A taxonomy is a naming system. The selector in the bar above the concept list chooses which one
			you are working in: it decides which names the list shows and which name a concept is
			presented under.
		</p>
		<p>
			It is a <strong>durable preference</strong> — your choice is remembered between visits, so you
			stay in your own vocabulary without re-picking it. It also appears in the URL as
			<code>?taxonomy=&lt;key&gt;</code>, which is how you send someone a link that opens in a
			specific one.
		</p>
		<p>
			Switching taxonomies does not change what exists, only what things are called. A concept with
			no name in the taxonomy you selected simply does not appear in that list — it is still there,
			reachable by id or under another of its names.
		</p>
		<p>
			On a <strong>concept page</strong> the selector stays on the concept: switching takes you to
			the same concept's page under the name it carries in the taxonomy you picked, keeping the date
			lens and the open source tab. Taxonomies the concept has no live name in are shown greyed out;
			picking one offers to
			<a href="/docs/editing#names" class="text-primary underline-offset-4 hover:underline"
				>register a name for it there</a
			>
			rather than navigating away.
		</p>
	</DocSection>

	<DocSection id="date" title="The as-of date lens">
		<p>
			<strong>“View as of…”</strong> next to the taxonomy selector rewinds the entire repository to a
			chosen date. It is not a filter on a column; it moves the whole lens — which names were registered
			then, and which version of each definition was current then. A calendar popover picks the date, capped
			at today.
		</p>
		<Alert.Root>
			<HistoryIcon />
			<Alert.Title>You are always told</Alert.Title>
			<Alert.Description>
				While a date is active, an amber strip sits under the top bar: "Viewing historical state as
				of …", with <strong>Back to current</strong> to clear it. The same clear is available as a
				small × beside the date button.
			</Alert.Description>
		</Alert.Root>
		<p>
			Unlike the taxonomy, the date is <strong>never persisted</strong>. It lives only in the URL
			(<code>?date=YYYY-MM-DD</code>, or the short <code>?d=</code>), which means it is shareable,
			clearable, and gone the next time you open the app fresh. Links you follow inside the app carry
			it along, so the lens stays applied while you navigate.
		</p>
		<p>
			The programmatic equivalent is the <code>date</code> parameter on an API read — see
			<a href="/docs/clients#curl" class="text-primary underline-offset-4 hover:underline"
				>Connecting clients</a
			>. Use it to reconstruct exactly what an analysis saw on the day it ran.
		</p>
	</DocSection>

	<DocSection id="links" title="Stable links">
		<p>
			Almost everything you can look at has a URL you can paste into a ticket or a paper. The ones
			worth knowing:
		</p>
		<Table.Root>
			<Table.Header>
				<Table.Row>
					<Table.Head class="w-80">URL</Table.Head>
					<Table.Head>Opens</Table.Head>
				</Table.Row>
			</Table.Header>
			<Table.Body>
				<Table.Row>
					<Table.Cell class="align-top font-mono text-xs">/concepts/tax/&lt;tax&gt;/&lt;name&gt;</Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						The concept under one of its names.
					</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="align-top font-mono text-xs">…?cid=42</Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						Pins which member of a group you mean — the unambiguous form.
					</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="align-top font-mono text-xs">…?source=&lt;key&gt;&amp;v=3</Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						One source's definition at exactly version 3.
					</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="align-top font-mono text-xs">…?source=&lt;key&gt;&amp;draft=17</Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						An open draft, overlaid on the published definition.
					</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="align-top font-mono text-xs">/concepts/id/42</Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						The concept by its permanent id; redirects to whatever it is currently called. The
						safest link of all — it survives every rename.
					</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="align-top font-mono text-xs">/files/&lt;source&gt;/&lt;uuid&gt;</Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						A data file's history and the concepts that read it.
					</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="align-top font-mono text-xs">/review?status=pending</Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						The review queue, filtered.
					</Table.Cell>
				</Table.Row>
			</Table.Body>
		</Table.Root>
		<p>
			On a concept's history, the copy button beside a version copies an API reference pinned to that
			version, ready to paste into code. That, not a screenshot of the JSON, is how you cite a
			definition.
		</p>
	</DocSection>
</DocPage>
