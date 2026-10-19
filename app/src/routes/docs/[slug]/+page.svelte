<script lang="ts">
	import DocPage from "$lib/components/docs/DocPage.svelte";
	import DocBodyView from "$lib/components/docs/DocBodyView.svelte";

	let { data } = $props();
</script>

<DocPage chapter={data.chapter.meta} prev={data.chapter.prev} next={data.chapter.next}>
	<DocBodyView body={data.chapter.body} />
</DocPage>
