import tailwindcss from '@tailwindcss/vite';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig, type Plugin } from 'vite';
import fs from 'node:fs';
import path from 'node:path';

/**
 * Dev-only brand overlay: with BRAND_DIR set, `pnpm dev` serves /brand/* from that
 * directory instead of static/brand — the same swap a deployment does by bind-mounting
 * over the built app's /brand. Lets you develop against your institution's fonts and
 * imagery without touching the checkout (e.g. BRAND_DIR=../../deploy-repo/brand pnpm dev).
 * No effect on builds or when BRAND_DIR is unset.
 */
function brandDirOverlay(): Plugin {
	const dir = process.env.BRAND_DIR;
	return {
		name: 'brand-dir-overlay',
		apply: 'serve',
		configureServer(server) {
			if (!dir) return;
			const root = path.resolve(dir);
			const types: Record<string, string> = {
				'.css': 'text/css',
				'.ttf': 'font/ttf',
				'.woff2': 'font/woff2',
				'.png': 'image/png',
				'.jpg': 'image/jpeg',
				'.jpeg': 'image/jpeg',
				'.svg': 'image/svg+xml',
			};
			server.middlewares.use('/brand', (req, res, next) => {
				const rel = decodeURIComponent((req.url ?? '/').split('?')[0]);
				const file = path.join(root, rel);
				// stay inside the overlay dir, fall through to static/brand for misses
				if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
					return next();
				}
				res.setHeader('Content-Type', types[path.extname(file).toLowerCase()] ?? 'application/octet-stream');
				fs.createReadStream(file).pipe(res);
			});
		},
	};
}

export default defineConfig({ plugins: [tailwindcss(), sveltekit(), brandDirOverlay()] });
