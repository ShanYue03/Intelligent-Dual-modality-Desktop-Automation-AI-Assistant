export {};

declare global {
  interface Window {
    desktop?: {
      platform: string;
      isCompact: boolean;
      isCompactModeActive?: () => Promise<boolean>;
      enterCompact: (opts?: { animate?: boolean; routePath?: string }) => Promise<void>;
      exitCompact: () => Promise<void>;
    };
  }
}
