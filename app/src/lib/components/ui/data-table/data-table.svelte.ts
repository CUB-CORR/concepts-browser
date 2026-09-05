// The Svelte 5 adapter for `@tanstack/table-core` that the shadcn-svelte data-table recipe
// uses. table-core is framework-agnostic: it wants a plain options object and re-reads it
// whenever it recomputes. `mergeObjects` hands it a proxy that forwards every read to the
// caller's (reactive) getters, so a rune the caller declared stays the source of truth and the
// table follows it — instead of the table holding a snapshot taken once at construction.
import {
	type RowData,
	type TableOptions,
	type TableOptionsResolved,
	type TableState,
	createTable,
} from "@tanstack/table-core";

/** A read-through view over several objects, last one wins. Reads stay lazy, so a getter on
 *  any source (a `$derived`, a `$state`) is evaluated at access time and tracks as a dependency. */
function mergeObjects<T extends object>(...sources: (object | undefined)[]): T {
	const find = (prop: string | symbol) => {
		for (let i = sources.length - 1; i >= 0; i--) {
			const source = sources[i];
			if (source && prop in source) {
				const value = (source as Record<string | symbol, unknown>)[prop];
				if (value !== undefined) return { value };
			}
		}
		return undefined;
	};
	return new Proxy({} as T, {
		get: (_target, prop) => find(prop)?.value,
		has: (_target, prop) => sources.some((source) => source && prop in source),
		ownKeys: () => [
			...new Set(sources.flatMap((source) => (source ? Reflect.ownKeys(source) : []))),
		],
		getOwnPropertyDescriptor: (_target, prop) => {
			const hit = find(prop);
			return hit && { configurable: true, enumerable: true, value: hit.value };
		},
	});
}

export function createSvelteTable<TData extends RowData>(options: TableOptions<TData>) {
	const resolved: TableOptionsResolved<TData> = mergeObjects(
		{
			state: {},
			onStateChange() {},
			renderFallbackValue: null,
			mergeOptions: (defaultOptions: TableOptions<TData>, opts: Partial<TableOptions<TData>>) =>
				mergeObjects<TableOptions<TData>>(defaultOptions, opts),
		},
		options,
	);

	const table = createTable(resolved);
	let state = $state<Partial<TableState>>(table.initialState);

	function updateOptions() {
		table.setOptions((prev) =>
			mergeObjects(prev, options, {
				state: mergeObjects(state, options.state ?? {}),
				onStateChange: (updater: unknown) => {
					state = updater instanceof Function ? updater(state) : mergeObjects(state, updater as object);
					options.onStateChange?.(updater as never);
				},
			}),
		);
	}

	updateOptions();
	$effect.pre(updateOptions);

	return table;
}
