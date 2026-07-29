export function isCompactWindow(): boolean {
  return Boolean(window.desktop?.isCompact);
}

export async function isCompactModeActive(): Promise<boolean> {
  if (window.desktop?.isCompactModeActive) {
    return window.desktop.isCompactModeActive();
  }
  return false;
}

export async function enterCompactMode(opts?: {
  animate?: boolean;
  routePath?: string;
}): Promise<void> {
  if (window.desktop?.enterCompact) {
    await window.desktop.enterCompact(opts || { animate: true });
  }
}

export async function exitCompactMode(): Promise<void> {
  if (window.desktop?.exitCompact) {
    await window.desktop.exitCompact();
  }
}
