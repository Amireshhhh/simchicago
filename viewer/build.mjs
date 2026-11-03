import { build } from 'esbuild';
import { cpSync, mkdirSync, existsSync } from 'node:fs';
mkdirSync('dist/data', { recursive: true });
await build({ entryPoints: ['src/main.js'], bundle: true, format: 'esm', target: 'es2022', minify: true, outfile: 'dist/app.js', logLevel: 'info' });
cpSync('index.html', 'dist/index.html'); cpSync('app.css', 'dist/app.css');
if (!existsSync('dist/data/run.json')) console.warn('dist/data/run.json missing: run `python -m simchi.cli export`');

// Self-contained page for publishing as a claude.ai artifact (CSS and JS inlined; data fetched
// from the published file data/run.json). The skeleton (doctype/head/body) is added at publish.
import { readFileSync, writeFileSync } from 'node:fs';
const html = readFileSync('index.html', 'utf8');
const css = readFileSync('app.css', 'utf8').replace(/:root \{/, ':root {\n  color-scheme: dark;');
const js = readFileSync('dist/app.js', 'utf8').replace(/<\/script/gi, '<\\/script');
const body = html.slice(html.indexOf('<body>') + 6, html.indexOf('<script type="module"'));
const page = `<title>SimChicago City Viewer</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,400..800&display=swap" rel="stylesheet">
<style>${css}</style>
${body}<script type="module">${js}</script>
`;
writeFileSync('dist/artifact.html', page);
console.log('dist/artifact.html', (page.length / 1024).toFixed(0) + ' KB');
