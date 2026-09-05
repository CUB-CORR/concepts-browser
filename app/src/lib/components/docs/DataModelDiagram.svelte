<script lang="ts">
	// The pointer-based taxonomy model, drawn. Three layers side by side — taxonomy pointers,
	// concepts, source configs — with an SVG overlay that connects the cards. The overlay is
	// decorative: everything it says is also said by the numbered reading notes below it.
	type Edge = {
		f: string;
		t: string;
		cls: "pointer" | "deprecated" | "config" | "successor";
		sdy?: number;
		tdy?: number;
		vertical?: boolean;
		label?: string;
	};

	const edges: Edge[] = [
		{ f: "p1", t: "c101", cls: "pointer", tdy: -9 },
		{ f: "p2", t: "c101", cls: "pointer", sdy: -7, tdy: 9 },
		{ f: "p2", t: "c102", cls: "pointer", sdy: 7, tdy: -9 },
		{ f: "p3", t: "c102", cls: "pointer", tdy: 9 },
		{ f: "p4", t: "c103", cls: "deprecated", tdy: -9 },
		{ f: "p5", t: "c103", cls: "pointer", tdy: 9 },
		{ f: "c101", t: "cfg101", cls: "config" },
		{ f: "c102", t: "cfg102", cls: "config" },
		{ f: "c103", t: "cfg103", cls: "config", sdy: -7 },
		{ f: "c103", t: "cfg103b", cls: "config", sdy: 7 },
		{ f: "c104", t: "c103", cls: "successor", vertical: true, label: "successor" }
	];

	let diagram = $state<HTMLDivElement | null>(null);
	let svg = $state<SVGSVGElement | null>(null);
	let paths = $state<SVGGElement | null>(null);

	const NS = "http://www.w3.org/2000/svg";

	function draw() {
		if (!diagram || !svg || !paths) return;
		const node = (id: string) => diagram!.querySelector<HTMLElement>(`[data-node="${id}"]`);

		const dr = diagram.getBoundingClientRect();
		svg.setAttribute("viewBox", `0 0 ${dr.width} ${dr.height}`);
		while (paths.firstChild) paths.removeChild(paths.firstChild);

		for (const e of edges) {
			const from = node(e.f);
			const to = node(e.t);
			if (!from || !to) continue;
			const a = from.getBoundingClientRect();
			const b = to.getBoundingClientRect();
			const p = document.createElementNS(NS, "path");
			p.setAttribute("class", `edge ${e.cls}`);
			p.setAttribute("marker-end", `url(#ah-${e.cls})`);

			let d: string;
			if (e.vertical) {
				const x1 = a.left - dr.left + a.width / 2;
				const y1 = a.top - dr.top - 2;
				const y2 = b.bottom - dr.top + 3;
				d = `M ${x1} ${y1} L ${x1} ${y2}`;
				if (e.label) {
					const t = document.createElementNS(NS, "text");
					t.setAttribute("class", "edge-label");
					t.setAttribute("x", String(x1 + 9));
					t.setAttribute("y", String((y1 + y2) / 2 + 3));
					t.textContent = e.label;
					paths.appendChild(t);
				}
			} else {
				const sx = a.right - dr.left + 2;
				const sy = a.top - dr.top + a.height / 2 + (e.sdy ?? 0);
				const tx = b.left - dr.left - 3;
				const ty = b.top - dr.top + b.height / 2 + (e.tdy ?? 0);
				const dx = (tx - sx) * 0.45;
				d =
					`M ${sx} ${sy}` +
					` C ${sx + dx} ${sy}, ${tx - dx} ${ty}` +
					`, ${tx} ${ty}`;
			}
			p.setAttribute("d", d);
			paths.appendChild(p);
		}
	}

	$effect(() => {
		if (!diagram) return;
		let raf: number | null = null;
		const schedule = () => {
			if (raf !== null) cancelAnimationFrame(raf);
			raf = requestAnimationFrame(draw);
		};
		window.addEventListener("resize", schedule);
		const ro = new ResizeObserver(schedule);
		ro.observe(diagram);
		// Web fonts land after first paint and change every card's height, so redraw once more.
		document.fonts?.ready.then(schedule).catch(() => {});
		draw();
		return () => {
			if (raf !== null) cancelAnimationFrame(raf);
			window.removeEventListener("resize", schedule);
			ro.disconnect();
		};
	});
</script>

<div class="cdm">
	<div class="scroller">
		<div class="diagram" bind:this={diagram}>
			<svg class="edges" bind:this={svg} aria-hidden="true">
				<defs>
					<marker
						id="ah-pointer"
						viewBox="0 0 10 10"
						refX="8"
						refY="5"
						markerWidth="7"
						markerHeight="7"
						orient="auto-start-reverse"
					>
						<path class="mk-pointer" d="M 0 1 L 9 5 L 0 9 z"></path>
					</marker>
					<marker
						id="ah-deprecated"
						viewBox="0 0 10 10"
						refX="8"
						refY="5"
						markerWidth="7"
						markerHeight="7"
						orient="auto-start-reverse"
					>
						<path class="mk-deprecated" d="M 0 1 L 9 5 L 0 9 z"></path>
					</marker>
					<marker
						id="ah-config"
						viewBox="0 0 10 10"
						refX="8"
						refY="5"
						markerWidth="7"
						markerHeight="7"
						orient="auto-start-reverse"
					>
						<path class="mk-config" d="M 0 1 L 9 5 L 0 9 z"></path>
					</marker>
					<marker
						id="ah-successor"
						viewBox="0 0 10 10"
						refX="8"
						refY="5"
						markerWidth="7"
						markerHeight="7"
						orient="auto-start-reverse"
					>
						<path class="mk-successor" d="M 0 1 L 9 5 L 0 9 z"></path>
					</marker>
				</defs>
				<g bind:this={paths}></g>
			</svg>

			<header class="colhead h-ptr">
				<div class="layer">Layer 1 · Taxonomy pointers</div>
				<div class="tbl">table <code>concept_taxonomy</code> — keyed by (taxonomy, identifier)</div>
				<div class="hint">append-only · created_at / deprecated_at · no uniqueness</div>
			</header>
			<header class="colhead h-con">
				<div class="layer">Layer 2 · Concepts</div>
				<div class="tbl">table <code>concept</code> — immutable integer id</div>
				<div class="hint">description · clinical documentation · optional successor</div>
			</header>
			<header class="colhead h-cfg">
				<div class="layer">Layer 3 · Source configs</div>
				<div class="tbl">table <code>config</code> — per concept, per data source</div>
				<div class="hint">immutable versioned rows · JSON definition + python snippet</div>
				<div class="hint">version counter runs per concept, shared by its sources</div>
			</header>

			<div class="card pointer" data-node="p1">
				<span class="callout">1</span>
				<div class="card-top">
					<span class="chip tax">corr_v1</span><span class="chip origin">import</span>
				</div>
				<div class="ident">med_metoprolol</div>
			</div>
			<div class="card pointer" data-node="p2">
				<span class="callout">2</span>
				<div class="card-top">
					<span class="chip tax">ATC</span><span class="chip grp">group</span><span
						class="chip origin">import</span
					>
				</div>
				<div class="ident">C07AB02</div>
			</div>
			<div class="card pointer" data-node="p3">
				<div class="card-top">
					<span class="chip tax">corr_v1</span><span class="chip origin">import</span>
				</div>
				<div class="ident">med_metoprolol_retard</div>
			</div>
			<div class="card pointer is-deprecated dim" data-node="p4">
				<div class="card-top">
					<span class="chip tax">corr_v1</span><span class="chip depr">deprecated</span><span
						class="chip origin">import</span
					>
				</div>
				<div class="ident">lab_crea</div>
			</div>
			<div class="card pointer" data-node="p5">
				<span class="callout">3</span>
				<div class="card-top">
					<span class="chip tax">corr_v1</span><span class="chip origin">user</span>
				</div>
				<div class="ident">lab_creatinine</div>
			</div>

			<div class="card concept" data-node="c101">
				<div class="card-top"><span class="chip cid">#101</span></div>
				<div class="ctitle">Metoprolol</div>
				<div class="cmeta">description · clinical documentation</div>
			</div>
			<div class="card concept" data-node="c102">
				<div class="card-top"><span class="chip cid">#102</span></div>
				<div class="ctitle">Metoprolol retard</div>
				<div class="cmeta">description · clinical documentation</div>
			</div>
			<div class="card concept" data-node="c103">
				<div class="card-top"><span class="chip cid">#103</span></div>
				<div class="ctitle">Serum creatinine</div>
				<div class="cmeta">description · clinical documentation</div>
			</div>
			<div class="card concept dim" data-node="c104">
				<span class="callout">4</span>
				<div class="card-top">
					<span class="chip cid">#104</span><span class="chip depr">deprecated</span>
				</div>
				<div class="ctitle">Creatinine (legacy)</div>
				<div class="cmeta"><code>successor_id → #103</code></div>
			</div>

			<div class="card config" data-node="cfg101">
				<div class="card-top"><span class="chip src">cub_hdp</span></div>
				<ul class="vers">
					<li><span class="v">v1</span> definition + snippet</li>
					<li><span class="v">v2</span> <span class="chip bump">auto-bumped by sync importer</span></li>
				</ul>
			</div>
			<div class="card config" data-node="cfg102">
				<div class="card-top"><span class="chip src">cub_hdp</span></div>
				<ul class="vers">
					<li><span class="v">v1</span> definition + snippet</li>
				</ul>
			</div>
			<div class="card config" data-node="cfg103">
				<div class="card-top"><span class="chip src">cub_hdp</span></div>
				<ul class="vers">
					<li><span class="v">v1</span> definition + snippet</li>
					<li><span class="v">v2</span> definition + snippet</li>
					<li><span class="v">v4</span> definition + snippet</li>
				</ul>
			</div>
			<div class="card config" data-node="cfg103b">
				<div class="card-top"><span class="chip src">reprodicu</span></div>
				<ul class="vers">
					<li><span class="v">v3</span> definition + snippet</li>
				</ul>
			</div>
		</div>
	</div>

	<p class="rule">
		<b>IDs are identity · names are permanent lookup pointers · versions live inside the concept.</b>
		Version numbering (v1, v2, …) exists only in layer 3, runs per concept rather than per source, and
		is never renumbered.
	</p>

	<div class="notes">
		<div class="note">
			<span class="n">1</span><span>
				<b>Simple 1:1.</b> <code>corr_v1/med_metoprolol</code> resolves to concept #101, whose
				<code>cub_hdp</code> config was auto-bumped to v2 when the sync importer detected a change.
			</span>
		</div>
		<div class="note">
			<span class="n">2</span><span>
				<b>Group — 1 name, N concepts.</b> <code>ATC/C07AB02</code> points at #101
				<em>and</em> #102. No uniqueness on (taxonomy, identifier); reading a name always returns a list.
			</span>
		</div>
		<div class="note">
			<span class="n">3</span><span>
				<b>Alias / rename — N names, 1 concept.</b> Rename = add pointer
				<code>lab_creatinine</code>, deprecate <code>lab_crea</code>. Old names resolve forever —
				pointers are append-only and never hard-deleted.
			</span>
		</div>
		<div class="note">
			<span class="n">4</span><span>
				<b>Concept deprecation.</b> #104 is deprecated at the concept level and forwards via
				<code>successor_id</code> to #103. Requested by editors, approved by reviewers holding
				<code>can_publish</code>.
			</span>
		</div>
	</div>

	<div class="legend">
		<span class="lg">
			<svg width="34" height="10" viewBox="0 0 34 10" aria-hidden="true"
				><line class="sw-line" x1="0" y1="5" x2="26" y2="5" stroke="var(--cdm-ptr)"></line><path
					d="M 26 1 L 33 5 L 26 9 z"
					fill="var(--cdm-ptr)"
				></path></svg
			>
			pointer resolves to concept
		</span>
		<span class="lg">
			<svg width="34" height="10" viewBox="0 0 34 10" aria-hidden="true"
				><line
					class="sw-line"
					x1="0"
					y1="5"
					x2="26"
					y2="5"
					stroke="var(--cdm-muted)"
					stroke-dasharray="4 3"
				></line><path d="M 26 1 L 33 5 L 26 9 z" fill="var(--cdm-muted)"></path></svg
			>
			<span>deprecated pointer — <span class="strike">struck through</span>, still resolves</span>
		</span>
		<span class="lg">
			<svg width="34" height="10" viewBox="0 0 34 10" aria-hidden="true"
				><line
					class="sw-line"
					x1="0"
					y1="5"
					x2="26"
					y2="5"
					stroke="var(--cdm-succ)"
					stroke-dasharray="5 3"
				></line><path d="M 26 1 L 33 5 L 26 9 z" fill="var(--cdm-succ)"></path></svg
			>
			successor of a deprecated concept
		</span>
		<span class="lg"><span class="chip grp">group</span> one identifier, several concepts</span>
		<span class="lg"
			><span class="chip depr">deprecated</span> pointer stays resolvable; concept forwards to successor</span
		>
		<span class="lg"
			><span class="chip origin">user</span>&thinsp;/&thinsp;<span class="chip origin">import</span>
			pointer origin: added in-app vs managed by the importer</span
		>
	</div>
</div>

<style>
	/* Neutrals come from the app theme so the diagram sits natively on the docs page; the four
	   accents (pointer blue / concept purple / config green / successor orange) are the diagram's
	   own semantics and are kept, with a dark variant under the app's `.dark` class. */
	.cdm {
		--cdm-surface: var(--card);
		--cdm-ink: var(--foreground);
		--cdm-ink-2: var(--muted-foreground);
		--cdm-muted: color-mix(in oklab, var(--muted-foreground) 78%, var(--background));
		--cdm-line: var(--border);
		--cdm-border: var(--border);

		--cdm-ptr: #2a78d6;
		--cdm-ptr-ink: #1c5cab;
		--cdm-ptr-bg: rgba(42, 120, 214, 0.09);

		--cdm-con: #4a3aa7;
		--cdm-con-ink: #4a3aa7;
		--cdm-con-bg: rgba(74, 58, 167, 0.07);

		--cdm-cfg: #1baf7a;
		--cdm-cfg-ink: #0b7a52;
		--cdm-cfg-bg: rgba(27, 175, 122, 0.1);

		--cdm-succ: #d95926;
		--cdm-succ-ink: #b04a1e;

		--cdm-depr-ink: #b3382f;
		--cdm-depr-bg: rgba(211, 59, 59, 0.08);

		color: var(--cdm-ink);
		font: 400 14px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
	}

	:global(.dark) .cdm {
		--cdm-ptr: #3987e5;
		--cdm-ptr-ink: #86b6ef;
		--cdm-ptr-bg: rgba(57, 135, 229, 0.14);

		--cdm-con: #9085e9;
		--cdm-con-ink: #aea6f0;
		--cdm-con-bg: rgba(144, 133, 233, 0.12);

		--cdm-cfg: #199e70;
		--cdm-cfg-ink: #4cc79a;
		--cdm-cfg-bg: rgba(25, 158, 112, 0.14);

		--cdm-succ: #eb6834;
		--cdm-succ-ink: #f0895c;

		--cdm-depr-ink: #e66767;
		--cdm-depr-bg: rgba(230, 103, 103, 0.12);
	}

	.cdm code {
		font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
	}

	/* ---------- diagram ---------- */
	/* left/top padding keeps the overhanging callout chips inside the clip box */
	.scroller {
		overflow-x: auto;
		padding: 12px 2px 4px 14px;
		margin: -12px -2px 0 -14px;
	}
	.diagram {
		position: relative;
		display: grid;
		grid-template-columns: 1fr 1fr 1fr;
		column-gap: 84px;
		row-gap: 14px;
		min-width: 900px;
	}
	svg.edges {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		pointer-events: none;
		overflow: visible;
	}
	:global(.cdm .edge) {
		fill: none;
		stroke-width: 1.6px;
	}
	:global(.cdm .edge.pointer) {
		stroke: var(--cdm-ptr);
	}
	:global(.cdm .edge.deprecated) {
		stroke: var(--cdm-muted);
		stroke-dasharray: 5 4;
		opacity: 0.85;
	}
	:global(.cdm .edge.config) {
		stroke: var(--cdm-cfg);
		opacity: 0.75;
	}
	:global(.cdm .edge.successor) {
		stroke: var(--cdm-succ);
		stroke-dasharray: 6 4;
		stroke-width: 1.8px;
	}
	.mk-pointer {
		fill: var(--cdm-ptr);
	}
	.mk-deprecated {
		fill: var(--cdm-muted);
	}
	.mk-config {
		fill: var(--cdm-cfg);
	}
	.mk-successor {
		fill: var(--cdm-succ);
	}
	:global(.cdm .edge-label) {
		font: 600 10px ui-sans-serif, system-ui, sans-serif;
		letter-spacing: 0.07em;
		text-transform: uppercase;
		fill: var(--cdm-succ-ink);
	}

	.colhead {
		min-width: 0;
		padding-bottom: 4px;
		border-bottom: 1px solid var(--cdm-line);
	}
	.colhead .layer {
		font-size: 11px;
		font-weight: 650;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}
	.colhead.h-ptr .layer {
		color: var(--cdm-ptr-ink);
	}
	.colhead.h-con .layer {
		color: var(--cdm-con-ink);
	}
	.colhead.h-cfg .layer {
		color: var(--cdm-cfg-ink);
	}
	.colhead .tbl {
		font-size: 11.5px;
		color: var(--cdm-ink-2);
	}
	.colhead .tbl code {
		font-size: 11px;
	}
	.colhead .hint {
		font-size: 11px;
		color: var(--cdm-muted);
		margin-top: 1px;
	}

	.card {
		position: relative;
		background: var(--cdm-surface);
		border: 1px solid var(--cdm-border);
		border-radius: 6px;
		padding: 8px 10px 9px;
		min-width: 0;
	}
	.card.pointer {
		border-left: 3px solid var(--cdm-ptr);
	}
	.card.concept {
		border-left: 3px solid var(--cdm-con);
	}
	.card.config {
		border-left: 3px solid var(--cdm-cfg);
	}
	.card.dim {
		opacity: 0.72;
	}

	.card-top {
		display: flex;
		align-items: center;
		gap: 6px;
		flex-wrap: wrap;
		margin-bottom: 3px;
	}
	.chip {
		display: inline-block;
		font-size: 10px;
		font-weight: 600;
		letter-spacing: 0.05em;
		border-radius: 4px;
		padding: 1px 6px;
		white-space: nowrap;
	}
	.chip.tax {
		background: var(--cdm-ptr-bg);
		color: var(--cdm-ptr-ink);
		font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
	}
	.chip.cid {
		background: var(--cdm-con-bg);
		color: var(--cdm-con-ink);
		font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
		font-size: 11px;
	}
	.chip.src {
		background: var(--cdm-cfg-bg);
		color: var(--cdm-cfg-ink);
		font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
	}
	.chip.origin {
		border: 1px solid var(--cdm-border);
		color: var(--cdm-muted);
		text-transform: uppercase;
		letter-spacing: 0.07em;
		margin-left: auto;
	}
	.chip.grp {
		background: var(--cdm-con-bg);
		color: var(--cdm-con-ink);
		text-transform: uppercase;
		letter-spacing: 0.07em;
	}
	.chip.depr {
		background: var(--cdm-depr-bg);
		color: var(--cdm-depr-ink);
		text-transform: uppercase;
		letter-spacing: 0.07em;
	}
	.chip.bump {
		background: var(--cdm-ptr-bg);
		color: var(--cdm-ptr-ink);
		font-weight: 500;
		letter-spacing: 0;
	}
	/* in the legend the origin chips sit inline, not pushed to a card's right edge */
	.legend .chip.origin {
		margin-left: 0;
	}

	.ident {
		font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
		font-size: 13px;
		font-weight: 500;
		overflow-wrap: anywhere;
	}
	.is-deprecated .ident {
		text-decoration: line-through;
		color: var(--cdm-muted);
	}
	.ctitle {
		font-size: 13.5px;
		font-weight: 600;
	}
	.cmeta {
		font-size: 11px;
		color: var(--cdm-muted);
		margin-top: 2px;
	}
	.cmeta code {
		font-size: 10.5px;
	}

	ul.vers {
		list-style: none;
		margin: 2px 0 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 3px;
	}
	ul.vers li {
		display: flex;
		align-items: baseline;
		gap: 7px;
		font-size: 11.5px;
		color: var(--cdm-ink-2);
	}
	ul.vers .v {
		font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
		font-size: 11px;
		font-weight: 600;
		color: var(--cdm-cfg-ink);
		background: var(--cdm-cfg-bg);
		border-radius: 4px;
		padding: 0 5px;
		font-variant-numeric: tabular-nums;
	}

	.callout {
		position: absolute;
		top: -9px;
		left: -12px;
		width: 18px;
		height: 18px;
		border-radius: 50%;
		background: var(--cdm-ink);
		color: var(--background);
		font-size: 11px;
		font-weight: 650;
		display: flex;
		align-items: center;
		justify-content: center;
		font-variant-numeric: tabular-nums;
	}

	/* grid placement -- row 1 is the headers */
	.h-ptr {
		grid-column: 1;
		grid-row: 1;
	}
	.h-con {
		grid-column: 2;
		grid-row: 1;
	}
	.h-cfg {
		grid-column: 3;
		grid-row: 1;
	}
	[data-node="p1"] {
		grid-column: 1;
		grid-row: 2;
	}
	[data-node="p2"] {
		grid-column: 1;
		grid-row: 3;
	}
	[data-node="p3"] {
		grid-column: 1;
		grid-row: 4;
	}
	[data-node="p4"] {
		grid-column: 1;
		grid-row: 5;
	}
	[data-node="p5"] {
		grid-column: 1;
		grid-row: 6;
	}
	[data-node="c101"] {
		grid-column: 2;
		grid-row: 2 / 4;
		align-self: center;
	}
	[data-node="c102"] {
		grid-column: 2;
		grid-row: 4;
		align-self: center;
	}
	[data-node="c103"] {
		grid-column: 2;
		grid-row: 5 / 7;
		align-self: center;
	}
	[data-node="c104"] {
		grid-column: 2;
		grid-row: 7;
		margin-top: 30px;
	}
	[data-node="cfg101"] {
		grid-column: 3;
		grid-row: 2 / 4;
		align-self: center;
	}
	[data-node="cfg102"] {
		grid-column: 3;
		grid-row: 4;
		align-self: center;
	}
	[data-node="cfg103"] {
		grid-column: 3;
		grid-row: 5;
		align-self: end;
	}
	[data-node="cfg103b"] {
		grid-column: 3;
		grid-row: 6;
		align-self: start;
	}

	/* ---------- rule strapline ---------- */
	.rule {
		margin: 22px 0 0;
		border: 1px solid var(--cdm-border);
		border-left: 3px solid var(--cdm-ink);
		border-radius: 6px;
		background: var(--cdm-surface);
		padding: 9px 14px;
		font-size: 13px;
		font-weight: 550;
	}
	.rule b {
		font-weight: 650;
	}

	/* ---------- reading notes ---------- */
	.notes {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
		gap: 10px 22px;
		margin-top: 16px;
	}
	.note {
		display: flex;
		gap: 9px;
		font-size: 12.5px;
		color: var(--cdm-ink-2);
	}
	.note .n {
		flex: none;
		width: 18px;
		height: 18px;
		margin-top: 1px;
		border-radius: 50%;
		background: var(--cdm-ink);
		color: var(--background);
		font-size: 11px;
		font-weight: 650;
		display: flex;
		align-items: center;
		justify-content: center;
	}
	.note b {
		color: var(--cdm-ink);
		font-weight: 600;
	}
	.note code {
		font-size: 11px;
	}

	/* ---------- legend ---------- */
	.legend {
		margin-top: 20px;
		padding-top: 12px;
		border-top: 1px solid var(--cdm-line);
		display: flex;
		flex-wrap: wrap;
		gap: 7px 22px;
		font-size: 11.5px;
		color: var(--cdm-ink-2);
	}
	.lg {
		display: flex;
		align-items: center;
		gap: 7px;
		white-space: nowrap;
	}
	.lg svg {
		flex: none;
		display: block;
	}
	.lg .sw-line {
		stroke-width: 1.6px;
		fill: none;
	}
	.lg .strike {
		text-decoration: line-through;
		color: var(--cdm-muted);
	}
</style>
