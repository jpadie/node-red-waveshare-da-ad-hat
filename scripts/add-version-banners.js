#!/usr/bin/env node
/*
 Adds a single-line @version banner at the top of published files.
 - Targets: lib/**/*, nodes/**/*, python/**/*
 - File types: .js, .ts, .d.ts, .html, .py
 - Skips: source maps (*.map) and non-targeted types
 - Idempotent: updates existing banner if present; inserts otherwise
*/

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

function getRepoRoot() {
  return path.resolve(__dirname, '..');
}

function readPackageJson(repoRoot) {
  const pkgPath = path.join(repoRoot, 'package.json');
  const text = fs.readFileSync(pkgPath, 'utf8');
  return JSON.parse(text);
}

function getGitSha(repoRoot) {
  try {
    return execSync('git rev-parse --short HEAD', { cwd: repoRoot, stdio: ['ignore', 'pipe', 'ignore'] })
      .toString()
      .trim();
  } catch (_) {
    return 'unknown';
  }
}

function listFilesRecursively(startDir) {
  const files = [];
  if (!fs.existsSync(startDir)) return files;
  const stack = [startDir];
  while (stack.length) {
    const current = stack.pop();
    const stats = fs.statSync(current);
    if (stats.isDirectory()) {
      const entries = fs.readdirSync(current).map((e) => path.join(current, e));
      for (const entry of entries) stack.push(entry);
    } else if (stats.isFile()) {
      files.push(current);
    }
  }
  return files;
}

function getCommentStyleForFile(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === '.html' || ext === '.htm') return { type: 'html', open: '<!-- ', close: ' -->' };
  if (ext === '.py') return { type: 'line', prefix: '# ' };
  if (ext === '.js' || ext === '.ts' || ext === '.tsx' || ext === '.d.ts') return { type: 'line', prefix: '// ' };
  return null;
}

function buildBannerText(pkgName, version, timestampIso, gitSha, style) {
  const core = `@version ${pkgName} v${version} ${timestampIso} commit ${gitSha}`;
  if (style.type === 'html') return `${style.open}${core}${style.close}`;
  if (style.type === 'line') return `${style.prefix}${core}`;
  return core;
}

function replaceOrInsertBanner(original, banner, style) {
  const shebangMatch = original.startsWith('#!') ? original.split(/\n/, 1)[0] : null;
  const shebangLen = shebangMatch ? shebangMatch.length : 0;
  const hasShebang = Boolean(shebangMatch);

  const doctypeMatch = /^<!DOCTYPE [^>]+>\s*/i.exec(original);
  const doctypeLen = doctypeMatch ? doctypeMatch[0].length : 0;

  const insertionOffset = style.type === 'html' && doctypeMatch ? doctypeLen : (hasShebang ? shebangLen : 0);

  // Patterns to detect existing banner near top
  const topSlice = original.slice(0, 500); // only inspect the very top for speed
  let bannerRegex;
  if (style.type === 'html') {
    bannerRegex = /<!--\s*@version[^]*?-->\s*\n?/;
  } else if (style.type === 'line') {
    bannerRegex = /^(?:#!.*\n)?(?:(?:\/\/|#)\s*@version[^\n]*\n)/;
  }

  if (bannerRegex) {
    const match = bannerRegex.exec(topSlice);
    if (match) {
      // Replace existing banner
      const start = match.index;
      const end = start + match[0].length;
      return original.slice(0, start) + banner + '\n' + original.slice(end);
    }
  }

  // Insert new banner at the calculated insertion point
  return original.slice(0, insertionOffset) + (insertionOffset ? '\n' : '') + banner + '\n' + original.slice(insertionOffset);
}

function shouldProcessFile(filePath) {
  const lower = filePath.toLowerCase();
  if (lower.endsWith('.map')) return false;
  if (lower.endsWith('.pdf')) return false;
  const style = getCommentStyleForFile(filePath);
  return Boolean(style);
}

function main() {
  const repoRoot = getRepoRoot();
  const pkg = readPackageJson(repoRoot);
  const gitSha = getGitSha(repoRoot);
  const timestamp = new Date().toISOString();
  const targets = ['lib', 'nodes', 'python'].map((d) => path.join(repoRoot, d));

  const files = targets.flatMap((t) => listFilesRecursively(t)).filter(shouldProcessFile);

  let updated = 0;
  for (const filePath of files) {
    const style = getCommentStyleForFile(filePath);
    if (!style) continue;
    const banner = buildBannerText(pkg.name, pkg.version, timestamp, gitSha, style);
    const original = fs.readFileSync(filePath, 'utf8');
    const withBanner = replaceOrInsertBanner(original, banner, style);
    if (withBanner !== original) {
      fs.writeFileSync(filePath, withBanner, 'utf8');
      updated += 1;
    }
  }

  console.log(`add-version-banners: processed ${files.length} files, updated ${updated}`);
}

main();


