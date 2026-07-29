const { app, BrowserWindow, ipcMain, screen } = require("electron");
const path = require("path");
const { spawn } = require("child_process");
const http = require("http");
const fs = require("fs");

const PROJECT_ROOT = path.resolve(__dirname, "..");
const APP_ICON_ROUNDED = path.join(PROJECT_ROOT, "frontend", "src", "assets", "LogoRounded.png");
const APP_ICON = fs.existsSync(APP_ICON_ROUNDED)
  ? APP_ICON_ROUNDED
  : path.join(PROJECT_ROOT, "frontend", "src", "assets", "Logo.png");
const BACKEND_HOST = "127.0.0.1";
const BACKEND_PORT = 8765;
const DEV_URLS = ["http://127.0.0.1:5173", "http://localhost:5173"];
const isDev = process.env.ELECTRON_DEV === "1";

const COMPACT_WIDTH = 392;
const COMPACT_HEIGHT = 580;

let backendProcess = null;
let mainWindow = null;
let compactWindow = null;
let compactVisible = false;
let compactLoadedRoute = null;
let devUrlCache = null;

function backendReady() {
  return new Promise((resolve) => {
    const req = http.get(`http://${BACKEND_HOST}:${BACKEND_PORT}/api/health`, (res) => {
      resolve(res.statusCode === 200);
    });
    req.on("error", () => resolve(false));
    req.setTimeout(800, () => {
      req.destroy();
      resolve(false);
    });
  });
}

async function waitForBackend(maxMs = 120000) {
  const start = Date.now();
  while (Date.now() - start < maxMs) {
    if (await backendReady()) return true;
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

function devServerReady(url) {
  return new Promise((resolve) => {
    const req = http.get(url, (res) => {
      resolve(res.statusCode >= 200 && res.statusCode < 500);
    });
    req.on("error", () => resolve(false));
    req.setTimeout(800, () => {
      req.destroy();
      resolve(false);
    });
  });
}

async function waitForDevServer(maxMs = 60000) {
  const start = Date.now();
  while (Date.now() - start < maxMs) {
    for (const url of DEV_URLS) {
      if (await devServerReady(url)) return url;
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  return null;
}

function resolvePythonCommand() {
  const backendMain = path.join(PROJECT_ROOT, "backend", "main.py");

  if (process.env.PYTHON && fs.existsSync(process.env.PYTHON)) {
    return { cmd: process.env.PYTHON, args: [backendMain] };
  }

  const condaPrefix = process.env.CONDA_PREFIX;
  if (condaPrefix) {
    const condaPy = path.join(
      condaPrefix,
      process.platform === "win32" ? "python.exe" : "bin/python",
    );
    if (fs.existsSync(condaPy)) {
      return { cmd: condaPy, args: [backendMain] };
    }
  }

  const venvRoot = process.env.VIRTUAL_ENV;
  if (venvRoot) {
    const venvPy = path.join(
      venvRoot,
      process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
    );
    if (fs.existsSync(venvPy)) {
      return { cmd: venvPy, args: [backendMain] };
    }
  }

  return { cmd: "py", args: ["-3.11", backendMain] };
}

function startBackend() {
  const { cmd: py, args } = resolvePythonCommand();
  console.log("Starting backend:", py, args.join(" "));

  backendProcess = spawn(py, args, {
    cwd: PROJECT_ROOT,
    stdio: "inherit",
    windowsHide: true,
    env: { ...process.env },
  });

  backendProcess.on("error", (err) => {
    console.error("Failed to start Python backend:", err);
  });
}

function stopBackend() {
  if (backendProcess && !backendProcess.killed) {
    backendProcess.kill();
  }
  backendProcess = null;
}

function compactRouteUrl(devUrl, routePath = "/compact") {
  if (isDev) {
    const base = devUrl || DEV_URLS[0];
    return `${base}#${routePath}`;
  }
  const indexHtml = path.join(PROJECT_ROOT, "frontend", "dist", "index.html");
  return `file://${indexHtml.replace(/\\/g, "/")}#${routePath}`;
}

function defaultCompactBounds(fromBounds) {
  const display = screen.getDisplayNearestPoint(
    fromBounds ? { x: fromBounds.x, y: fromBounds.y } : screen.getPrimaryDisplay().workArea,
  );
  const work = display.workArea;
  const margin = 16;
  const x = work.x + work.width - COMPACT_WIDTH - margin;
  const y = work.y + work.height - COMPACT_HEIGHT - margin;
  return { x, y, width: COMPACT_WIDTH, height: COMPACT_HEIGHT };
}

function loadCompactContent(routePath = "/compact", { force = false } = {}) {
  if (!compactWindow || compactWindow.isDestroyed()) return;
  if (!force && compactLoadedRoute === routePath) return;
  const url = compactRouteUrl(devUrlCache, routePath);
  compactWindow.loadURL(url);
  compactLoadedRoute = routePath;
}

function createCompactWindow({ animate = true, routePath = "/compact" } = {}) {
  if (compactWindow && !compactWindow.isDestroyed()) {
    loadCompactContent(routePath);
    compactWindow.show();
    compactWindow.focus();
    compactWindow.setAlwaysOnTop(true, "screen-saver");
    compactVisible = true;
    return compactWindow;
  }

  const fromBounds = mainWindow && !mainWindow.isDestroyed() ? mainWindow.getBounds() : null;
  const target = defaultCompactBounds(fromBounds);

  compactWindow = new BrowserWindow({
    width: COMPACT_WIDTH,
    height: COMPACT_HEIGHT,
    x: target.x,
    y: target.y,
    show: false,
    frame: false,
    transparent: false,
    resizable: false,
    maximizable: false,
    minimizable: false,
    fullscreenable: false,
    alwaysOnTop: true,
    skipTaskbar: false,
    title: "Friday",
    icon: fs.existsSync(APP_ICON) ? APP_ICON : undefined,
    backgroundColor: "#0a0a0a",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      additionalArguments: ["--compact-window"],
      backgroundThrottling: false,
    },
  });

  compactWindow.setAlwaysOnTop(true, "screen-saver");

  compactWindow.on("closed", () => {
    compactWindow = null;
    compactVisible = false;
    compactLoadedRoute = null;
  });

  loadCompactContent(routePath);

  compactWindow.once("ready-to-show", () => {
    compactWindow.setBounds(target);
    compactWindow.show();
    compactWindow.focus();
    compactVisible = true;
  });

  return compactWindow;
}

function enterCompactMode(opts = {}) {
  const { animate = true, routePath = "/compact" } = opts;
  if (compactVisible && compactWindow && !compactWindow.isDestroyed()) {
    const routeChanged = compactLoadedRoute !== routePath;
    if (routeChanged) {
      loadCompactContent(routePath);
    }
    if (!compactWindow.isVisible()) {
      compactWindow.show();
    }
    if (routeChanged) {
      compactWindow.focus();
    }
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.hide();
    }
    return;
  }

  if (mainWindow && !mainWindow.isDestroyed()) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.hide();
  }

  createCompactWindow({ animate, routePath });
}

function exitCompactMode() {
  if (compactWindow && !compactWindow.isDestroyed()) {
    compactWindow.close();
  }
  compactWindow = null;
  compactVisible = false;
  compactLoadedRoute = null;

  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.show();
    if (!mainWindow.isMaximized()) mainWindow.maximize();
    mainWindow.focus();
  }
}

function createWindow(devUrl) {
  devUrlCache = devUrl;
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    title: "Friday",
    icon: fs.existsSync(APP_ICON) ? APP_ICON : undefined,
    show: false,
    backgroundColor: "#1a1a1a",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.on("page-title-updated", (event) => {
    event.preventDefault();
    mainWindow.setTitle("Friday");
  });

  mainWindow.once("ready-to-show", () => {
    mainWindow.maximize();
    mainWindow.show();
  });

  mainWindow.on("minimize", () => {
    setImmediate(() => {
      if (!mainWindow || mainWindow.isDestroyed()) return;
      mainWindow.restore();
      enterCompactMode({ animate: true });
    });
  });

  if (isDev) {
    const url = devUrl || DEV_URLS[0];
    console.log("Loading UI from", url);
    mainWindow.loadURL(url);
  } else {
    const indexHtml = path.join(PROJECT_ROOT, "frontend", "dist", "index.html");
    if (!fs.existsSync(indexHtml)) {
      console.error("Frontend build missing. Run: npm run build --prefix frontend");
    }
    mainWindow.loadURL(`file://${indexHtml.replace(/\\/g, "/")}#/`);
  }

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

ipcMain.handle("compact:enter", (_event, opts) => {
  enterCompactMode(opts || {});
});

ipcMain.handle("compact:is-active", () => compactVisible);

ipcMain.handle("compact:exit", () => {
  exitCompactMode();
});

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (compactVisible && compactWindow) {
      compactWindow.focus();
      return;
    }
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(async () => {
    startBackend();
    const ok = await waitForBackend();
    if (!ok) {
      console.error("Backend did not start on port", BACKEND_PORT);
    }

    let devUrl = null;
    if (isDev) {
      devUrl = await waitForDevServer();
      if (!devUrl) {
        console.error(
          "Vite dev server not reachable. In another terminal run: npm run dev:frontend",
        );
        devUrl = DEV_URLS[0];
      }
    }

    createWindow(devUrl);
  });

  app.on("window-all-closed", () => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      return;
    }
    if (process.platform !== "darwin") {
      stopBackend();
      app.quit();
    }
  });

  app.on("before-quit", () => {
    stopBackend();
  });
}
