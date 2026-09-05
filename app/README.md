# Concepts Browser — frontend

SvelteKit (adapter-node) frontend for the Concepts Browser. See the repository root
README for the full picture; everything below assumes `pnpm install` in this directory.

```bash
pnpm dev        # dev server on :5173 (expects the API on localhost:8000)
pnpm build      # production build (served by `node build`)
pnpm check      # svelte-check
```

Useful env vars in dev: `API_INTERNAL_URL` (backend base URL), `APP_SHARED_SECRET`
(must match the API's), `BRAND_DIR` (serve /brand from another directory — see the root
README's Branding section), and the `PUBLIC_*` branding overrides from `example.env`.
