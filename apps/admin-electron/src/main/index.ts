import { app, BrowserWindow, session, shell } from "electron";
import { join } from "node:path";
import log from "electron-log/main";

import { registerIpcHandlers } from "@main/ipc";
import { getConfig } from "@main/config";

// ---------------------------------------------------------------------------
// Single instance — second launch focuses the existing window instead of
// spawning a new one.
// ---------------------------------------------------------------------------
if (!app.requestSingleInstanceLock()) {
  app.quit();
  process.exit(0);
}

// ---------------------------------------------------------------------------
// Logging — electron-log writes to a platform-appropriate user-data path:
//   macOS:   ~/Library/Logs/plynth-admin/main.log
//   Win:     %USERPROFILE%\AppData\Roaming\plynth-admin\logs\main.log
//   Linux:   ~/.config/plynth-admin/logs/main.log
// File logs are level=info and up; console logs (dev) are level=debug.
// ---------------------------------------------------------------------------
log.initialize();
log.transports.file.level    = "info";
log.transports.console.level = app.isPackaged ? "warn" : "debug";
log.transports.file.maxSize  = 5 * 1024 * 1024; // 5 MB rotation
process.on("uncaughtException",  err => log.error("uncaughtException",  err));
process.on("unhandledRejection", err => log.error("unhandledRejection", err));

let mainWindow: BrowserWindow | null = null;

function createMainWindow(): void {
  mainWindow = new BrowserWindow({
    width:  1280,
    height: 800,
    minWidth:  960,
    minHeight: 600,
    show:   false,                                // show on `ready-to-show`
    title:  "Plynth Admin",
    backgroundColor: "#0b0d12",                   // matches Mantine dark
    autoHideMenuBar: true,
    webPreferences: {
      preload:           join(__dirname, "../preload/index.cjs"),
      contextIsolation:  true,                    // mandatory (security)
      nodeIntegration:   false,                   // mandatory (security)
      sandbox:           true,                    // mandatory (security)
      webSecurity:       true,
      devTools:          !app.isPackaged,
    },
  });

  mainWindow.once("ready-to-show", () => mainWindow?.show());
  mirrorRendererConsole(mainWindow);

  // External links open in the user's browser, never in our renderer.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  // Block any in-page navigation away from our own dev URL / file:// — the
  // renderer should only ever load our own bundle.
  mainWindow.webContents.on("will-navigate", (event, url) => {
    const allowed = process.env.ELECTRON_RENDERER_URL ?? "file://";
    if (!url.startsWith(allowed)) event.preventDefault();
  });

  if (process.env.ELECTRON_RENDERER_URL) {
    mainWindow.loadURL(process.env.ELECTRON_RENDERER_URL);
    mainWindow.webContents.openDevTools({ mode: "detach" });
  } else {
    mainWindow.loadFile(join(__dirname, "../renderer/index.html"));
  }

  mainWindow.on("closed", () => { mainWindow = null; });
}

function installCsp(): void {
  // Lock the renderer down so an XSS can't reach beyond our own bundle +
  // the configured platform API. In dev, Vite's HMR client + React Refresh
  // inject inline module scripts and use eval; we relax script-src for the
  // dev origin only, while keeping the packaged build strict.
  const baseUrl = getConfig().baseUrl;
  const apiOrigin = new URL(baseUrl).origin;
  const isDev = !app.isPackaged;

  const scriptSrc = isDev
    ? "script-src 'self' 'unsafe-inline' 'unsafe-eval'"
    : "script-src 'self'";

  session.defaultSession.webRequest.onHeadersReceived((details, cb) => {
    cb({
      responseHeaders: {
        ...details.responseHeaders,
        "Content-Security-Policy": [[
          "default-src 'self'",
          scriptSrc,
          "style-src 'self' 'unsafe-inline'",     // Mantine inlines runtime CSS
          "img-src 'self' data: blob:",
          `connect-src 'self' ${apiOrigin} ws: wss: http://localhost:* ws://localhost:*`,
          "font-src 'self' data:",
          "frame-ancestors 'none'",
          "base-uri 'self'",
          "object-src 'none'",
        ].join("; ")],
      },
    });
  });
}

function mirrorRendererConsole(win: BrowserWindow): void {
  // Surface renderer console.error / unhandled errors into the terminal +
  // electron-log file so blank-screen / crash debugging doesn't require
  // popping DevTools.
  win.webContents.on("console-message", (_e, level, message, line, source) => {
    if (level >= 2) {
      // 0=verbose 1=info 2=warning 3=error
      log.warn("renderer.console", { level, message, line, source });
    }
  });
  win.webContents.on("render-process-gone", (_e, details) => {
    log.error("renderer.process_gone", details);
  });
  win.webContents.on("did-fail-load", (_e, code, desc, url) => {
    log.error("renderer.did_fail_load", { code, desc, url });
  });
}

// ---------------------------------------------------------------------------
// Permission gates — deny anything we don't explicitly use.
// ---------------------------------------------------------------------------
function lockDownPermissions(): void {
  session.defaultSession.setPermissionRequestHandler((_wc, _perm, cb) => cb(false));
  session.defaultSession.setPermissionCheckHandler(() => false);
}

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------

app.on("second-instance", () => {
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  }
});

app.whenReady().then(() => {
  log.info("app.ready", { version: app.getVersion(), platform: process.platform });
  installCsp();
  lockDownPermissions();
  registerIpcHandlers();
  createMainWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createMainWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

// Hard reject all child windows.
app.on("web-contents-created", (_e, contents) => {
  contents.setWindowOpenHandler(() => ({ action: "deny" }));
});
