<script lang="ts">
	import DocPage from "$lib/components/docs/DocPage.svelte";
	import DocSection from "$lib/components/docs/DocSection.svelte";
	import AppLink from "$lib/components/docs/AppLink.svelte";
	import Cap from "$lib/components/docs/Cap.svelte";
	import CodeBlock from "$lib/components/CodeBlock.svelte";
	import * as Alert from "$lib/components/ui/alert";
	import * as Table from "$lib/components/ui/table";
	import TriangleAlertIcon from "@lucide/svelte/icons/triangle-alert";
	import InfoIcon from "@lucide/svelte/icons/info";
	import LockIcon from "@lucide/svelte/icons/lock";

	const snippet = `import pandas as pd

def postcode_region(var, cohort):
    # getfile() takes the file's uuid — never its path. The uuid is stable across
    # renames, which is what keeps an old published version reproducible.
    mapping = pd.read_csv(getfile("6f1e0c2a-1111-5222-8333-444455556666"))
    var.data = var.data.merge(mapping, on="postcode", how="left")
    return var.data`;
</script>

<DocPage slug="files">
	<DocSection id="what" title="What a data file is">
		<p>
			Some definitions cannot be expressed in JSON and code alone: they need a lookup table, a
			mapping of codes to categories, a fitted model. Those are <strong>data files</strong>. They
			live in the repository next to the definitions that read them, versioned the same way, so a
			published concept version stays reproducible even after the table behind it is corrected.
		</p>
		<p>
			A file belongs to <strong>one source</strong>. There is no global file list — picking the
			source is the first step, not a filter, which is why
			<AppLink href="/files">the files area</AppLink> opens on a card per source rather than on a table
			of files.
		</p>
	</DocSection>

	<DocSection id="library" title="A source's library">
		<p>
			Opening a source card takes you to that source's library, <code>/files/&lt;source&gt;</code>.
			Each row is a file as it stands now: its path, its size, its current version number, when and
			by whom it was last updated, and — the number that matters most — how many concepts'
			<em>current published</em> definitions read it.
		</p>
		<p>
			Opening a file, <code>/files/&lt;source&gt;/&lt;uuid&gt;</code>, gives you its full version
			history (each version with its own path, digest, size, author and message), the list of
			concepts that reference it, and a download for any version.
		</p>
		<Alert.Root>
			<LockIcon />
			<Alert.Title>Metadata and bytes are gated differently</Alert.Title>
			<Alert.Description>
				Everything <em>about</em> a file — that it exists, its path, size, digest, its versions, who
				changed it, which concepts read it — is <Cap cap="can_read" />. The
				<strong>contents</strong> are <Cap cap="can_read_detail" />. Without it the libraries and
				histories read exactly as they do for anyone else, but the download controls are replaced by
				a lock saying "Download requires read-detail access" rather than offering a link that would
				fail.
			</Alert.Description>
		</Alert.Root>
	</DocSection>

	<DocSection id="uuids" title="Uuids, paths and versions">
		<p>Three identifiers do three different jobs, and conflating them is the usual mistake:</p>
		<Table.Root>
			<Table.Header>
				<Table.Row>
					<Table.Head class="w-32">Thing</Table.Head>
					<Table.Head>What it is</Table.Head>
				</Table.Row>
			</Table.Header>
			<Table.Body>
				<Table.Row>
					<Table.Cell class="align-top font-medium">uuid</Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						The file's permanent identity. It never changes — not when the file is renamed, not
						when its contents are replaced. This is what a snippet references.
					</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="align-top font-medium">path</Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						The name the file is known by <em>in this source</em>, which a new version may change.
						A path is unique within a source at any one time, so a rename onto a name another
						file holds is refused and the page tells you which file is in the way.
					</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="align-top font-medium">version</Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						A per-file counter starting at 1. A concept version does not reference "the file", it
						references <em>this uuid at this version</em> — the pin that keeps it reproducible.
					</Table.Cell>
				</Table.Row>
			</Table.Body>
		</Table.Root>
		<Alert.Root>
			<InfoIcon />
			<Alert.Title>Uuids are derived, not random</Alert.Title>
			<Alert.Description>
				A file's uuid is computed from its source key and the path it was first created under, by a
				rule corr-vars shares. That is what lets a definition be written with the right
				<code>getfile("…")</code> call before the file has ever been uploaded here.
			</Alert.Description>
		</Alert.Root>
	</DocSection>

	<DocSection id="getfile" title="Reading a file from a snippet">
		<p>
			A Python snippet reaches its data through <code>getfile("&lt;uuid&gt;")</code>, which resolves
			to the bytes of the version this definition is pinned to. It is the only way in — a snippet
			never opens a path, and there is no relative-path mechanism.
		</p>
		<CodeBlock code={snippet} language="python" />
		<p>
			You do not have to type uuids. The
			<a href="/docs/editing#editor" class="text-primary underline-offset-4 hover:underline"
				>editor</a
			>
			has a file picker: it lists the current source's library and inserts the
			<code>getfile("…")</code> call for the file you choose. Which is also why reading a source's file
			list only needs <Cap cap="can_read" /> — everyone who can read a definition can see what it reads.
		</p>
		<p>
			The references are found by parsing the snippet, not by pattern-matching text: the word
			<code>getfile</code> inside a string or a comment is not a reference, and a call whose argument
			is computed rather than a literal is reported as something the repository cannot resolve for you
			(a warning, never a blocker). A <code>getfile("…")</code> naming no file in the source's library
			<em>is</em> a blocker — publishing is refused until it resolves.
		</p>
		<p>
			On a concept page, everything the current definition pins is listed alongside it with its
			version, and each entry links into the file library and offers the exact bytes that version
			was published against.
		</p>
	</DocSection>

	<DocSection id="upload" title="Uploading a new version">
		<p>
			On a source's library page you can add a file; on a file's own page you can replace it. Both
			ask for a path, the bytes, and an optional message describing the change. Both require
			<Cap cap="can_publish" /> — see
			<a href="#cascade" class="text-primary underline-offset-4 hover:underline">the cascade</a> for
			why an upload is a publish and not an edit.
		</p>
		<p>
			When the upload would replace an existing file, the dialog will not let you commit straight
			away: it first offers <strong>Review impact</strong>, which fetches and shows exactly which
			concepts read the file today. Only then does the button become
			<strong>Upload new version</strong>. Afterwards the toast tells you what actually happened — a
			version number, a rename, or nothing at all.
		</p>
		<p>Two conveniences worth knowing:</p>
		<ul class="ml-4 flex list-disc flex-col gap-1.5">
			<li>
				<strong>Identical bytes do nothing.</strong> If what you upload matches the current version exactly,
				no version is minted and nothing is cascaded; the page reports it as unchanged. Re-running an
				import is therefore safe.
			</li>
			<li>
				<strong>A new version may rename the file.</strong> Replacing a file while giving it a different
				path moves the path and keeps the uuid — so every snippet that references it keeps working, and
				every old version keeps the name it was uploaded under.
			</li>
		</ul>
		<p>
			Uploads are bounded: there is a maximum size and an allowed set of file types (tabular and
			serialised-data formats — CSV, TSV, Parquet, JSON, XLSX, pickles, plain text). Paths must be
			relative and well-formed; absolute paths, backslashes and <code>..</code> segments are refused.
		</p>
	</DocSection>

	<DocSection id="cascade" title="The cascade — what an upload does downstream">
		<p>
			This is the part to understand before you upload anything. A concept version pins a file
			version. If the file moves on and nothing else happens, every published definition would keep
			reading the old bytes forever — correct, but not what you wanted when you fixed a mapping
			table.
		</p>
		<p>
			So an upload <strong>cascades</strong>. For every concept whose current published definition
			reads the file, the repository publishes a <em>new version of that concept</em>: same JSON,
			same snippet, same type, only the pin moved to the new file version. The change is recorded
			with its own change type so history shows plainly that the definition itself did not change —
			its data did.
		</p>
		<Alert.Root variant="destructive">
			<TriangleAlertIcon />
			<Alert.Title>An upload publishes</Alert.Title>
			<Alert.Description>
				Uploading one file can mint versions of many concepts at once, visible immediately to every
				client that asks for "latest". The dialog tells you how many concepts read the file before
				you commit, and the result tells you exactly which ones were bumped. Read that number.
			</Alert.Description>
		</Alert.Root>
		<p>What the cascade deliberately does <em>not</em> touch:</p>
		<ul class="ml-4 flex list-disc flex-col gap-1.5">
			<li>
				<strong>Older concept versions.</strong> They keep their original pin. A study that pinned
				<code>v3</code> a year ago still resolves to the same bytes. That is the whole point.
			</li>
			<li>
				<strong>Drafts.</strong> An unpublished draft is never cascaded into. Instead the drift is shown
				to you: the draft says which files it pinned have since moved on, and publishing it pins the current
				versions.
			</li>
			<li>
				<strong>Retired concepts</strong> and auto-generated definitions, which are not versioned here.
			</li>
			<li>
				<strong>A concept already on the newest pin</strong> — cascading is idempotent, so nothing is
				double-versioned.
			</li>
		</ul>
	</DocSection>

	<DocSection id="retire" title="Retiring a file">
		<p>
			A file can be retired from its own page — <Cap cap="can_publish" />. It is always a soft
			retirement: nothing is deleted, and every version stays downloadable at the pins that reference
			it, because an old concept version must keep resolving.
		</p>
		<p>
			While any current published definition still reads the file, retiring it is refused and the
			page names the concepts standing in the way, so you know what to change first. Uploading again
			to a retired file's path brings it back.
		</p>
	</DocSection>
</DocPage>
