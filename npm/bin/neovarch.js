#!/usr/bin/env node
'use strict';
// `neovarch`: the Neovarch Agent command. Opens the desktop app with no arguments,
// otherwise runs the Neovarch core CLI (installed into ~/.neovarch on first use).
// Never uses or changes a Hermes Agent install (`hermes`, ~/.hermes).

const fs = require('fs');
const { spawn, spawnSync } = require('child_process');
const app = require('../lib/app');

const HELP = `Neovarch Agent ${app.PKG_VERSION}

Usage:
  neovarch                 Open the Neovarch Agent desktop app (downloads it on first run)
  neovarch desktop         Same as above
  neovarch <command> ...   Run the Neovarch core CLI (e.g. neovarch chat, neovarch --version)
  neovarch --install-core  Install or update the Neovarch core in ${app.CORE_DIR}
  neovarch --install-9router  Install 9Router (free default models) and start it
  neovarch router          9Router status (dashboard: ${app.ROUTER_DASHBOARD})
  neovarch --update        Re-download the desktop app and update the core
  neovarch --uninstall     Remove Neovarch Agent completely (${app.HOME_DIR})
  neovarch --help          Show this help

Environment:
  NEOVARCH_HOME            Data home (default ${app.HOME_DIR})
  NEOVARCH_VERSION         Desktop release tag, e.g. v1.4.6 (default: v${app.PKG_VERSION})
  NEOVARCH_REF             Git ref of the repo to take the core from (default: the release tag, else main)
  NEOVARCH_NO_9ROUTER      Set to skip installing 9Router
`;

async function ensureCore() {
  if (app.coreInstalled()) return true;
  try {
    await app.installCore();
  } catch (err) {
    app.log.warn(`could not install the Neovarch core: ${err.message}`);
    return false;
  }
  return app.coreInstalled();
}

function runCore(args) {
  const env = { ...process.env, NEOVARCH_HOME: app.HOME_DIR };
  const r = spawnSync(app.CORE_CLI, args, { stdio: 'inherit', env, windowsHide: false });
  return r.status ?? 1;
}

async function openDesktop(argv) {
  const target = app.detectTarget();
  if (target.unsupported) { app.printUnsupported(target.unsupported); return 1; }
  try {
    await app.installApp(target, {});
  } catch (err) {
    app.log.warn(`download failed: ${err.message}`);
    console.log(`      Download it manually from ${app.RELEASES_URL}/latest`);
    return 1;
  }
  if (!fs.existsSync(target.exe)) { app.log.warn(`app not found at ${target.exe}`); return 1; }
  // The desktop installs the core itself if it is missing; start that early when we can.
  if (!app.coreInstalled()) await ensureCore();
  const args = argv.filter((a) => a === '--no-sandbox' || !a.startsWith('--'));
  if (!args.includes('--no-sandbox') && app.needsNoSandbox()) args.unshift('--no-sandbox');
  const env = { ...process.env, NEOVARCH_HOME: app.HOME_DIR };
  for (const k of Object.keys(env)) if (k.startsWith('HERMES_')) delete env[k];
  const child = spawn(target.exe, args, { cwd: app.APP_DIR, detached: true, stdio: 'ignore', windowsHide: false, env });
  child.on('error', (err) => { app.log.warn(`could not start Neovarch Agent: ${err.message}`); process.exitCode = 1; });
  child.unref();
  return 0;
}

async function main(argv) {
  const first = argv[0];
  if (first === '-h' || first === '--help') { process.stdout.write(HELP); return 0; }
  if (first === '--uninstall') { app.uninstallAll(); return 0; }
  if (first === '--install-core') { await app.installCore(); return 0; }
  if (first === '--install-9router') {
    if (!(await ensureCore())) return 1;
    return app.install9Router() && app.setup9Router() ? 0 : 1;
  }
  if (first === '--update') {
    const target = app.detectTarget();
    if (!target.unsupported) await app.installApp(target, { force: true });
    await app.installCore();
    return 0;
  }
  if (argv.length === 0 || first === 'desktop' || first === '--no-sandbox') {
    return openDesktop(first === 'desktop' ? argv.slice(1) : argv);
  }
  if (!(await ensureCore())) return 1;
  return runCore(argv);
}

main(process.argv.slice(2)).then((code) => { if (code) process.exitCode = code; },
  (err) => { app.log.warn(err.message); process.exitCode = 1; });
