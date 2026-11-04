import { build } from 'esbuild';
import { cpSync, mkdirSync, existsSync, readFileSync, writeFileSync } from 'node:fs';

mkdirSync('dist/data', { recursive: true });
await build({ entryPoints: ['src/main.js'], bundle: true, format: 'esm', target: 'es2022', minify: true, outfile: 'dist/app.js', logLevel: 'info' });
cpSync('index.html', 'dist/index.html');
cpSync('app.css', 'dist/app.css');
if (!existsSync('dist/data/run.json')) console.warn('dist/data/run.json missing: run `python -m simchi.cli demo`');

// Self-contained page (CSS and JS inlined; data fetched from data/run.json next to it).
const html = readFileSync('index.html', 'utf8');
const css = readFileSync('app.css', 'utf8').replace(/:root \{/, ':root {\n  color-scheme: dark;');
const js = readFileSync('dist/app.js', 'utf8').replace(/<\/script/gi, '<\\/script');
const head = html.slice(html.indexOf('<head>') + 6, html.indexOf('<link rel="stylesheet"'));
const body = html.slice(html.indexOf('<body>') + 6, html.indexOf('<script type="module"'));
const page = `<!doctype html>\n<html lang="en">\n<head>${head}<style>${css}</style>\n</head>\n<body>${body}<script type="module">${js}</script>\n</body>\n</html>\n`;
writeFileSync('dist/standalone.html', page);
console.log('dist/standalone.html', (page.length / 1024).toFixed(0) + ' KB');
