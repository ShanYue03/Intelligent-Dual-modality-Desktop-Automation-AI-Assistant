import { useState, useCallback, useRef, useEffect } from "react";
import { Link } from "react-router";
import { fetchStatus, setGestureDominantHand, startGesture, stopGesture } from "../../lib/api";
import { useBackendSocket } from "../../hooks/useBackendSocket";
import { AUTO_START_GESTURE } from "../../hooks/useModuleSwitchListener";
import { Hand, Video, VideoOff, Settings, ArrowLeft } from "lucide-react";
import { motion, AnimatePresence } from "motion/react";

export function GestureControl({ compact = false }: { compact?: boolean }) {
  const [isCameraActive, setIsCameraActive] = useState(false);
  const [hasPreview, setHasPreview] = useState(false);
  const [detectedGesture, setDetectedGesture] = useState("");
  const [showSettings, setShowSettings] = useState(false);
  const [dominantHand, setDominantHand] = useState<"left" | "right">("right");
  const [error, setError] = useState<string | null>(null);
  const previewRef = useRef<HTMLImageElement>(null);
  const previewUrlRef = useRef<string | null>(null);
  const pendingPreviewRef = useRef<Blob | null>(null);
  const previewRafRef = useRef<number | null>(null);

  const clearPreview = useCallback(() => {
    if (previewRafRef.current !== null) {
      cancelAnimationFrame(previewRafRef.current);
      previewRafRef.current = null;
    }
    pendingPreviewRef.current = null;
    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current);
      previewUrlRef.current = null;
    }
    if (previewRef.current) previewRef.current.removeAttribute("src");
    setHasPreview(false);
  }, []);

  const flushPreviewFrame = useCallback(() => {
    previewRafRef.current = null;
    const jpeg = pendingPreviewRef.current;
    if (!jpeg || !previewRef.current) return;
    pendingPreviewRef.current = null;

    const url = URL.createObjectURL(jpeg);
    const previous = previewUrlRef.current;
    previewUrlRef.current = url;
    previewRef.current.src = url;
    if (previous) URL.revokeObjectURL(previous);
    setHasPreview(true);
  }, []);

  const applyPreviewFrame = useCallback(
    (jpeg: Blob) => {
      pendingPreviewRef.current = jpeg;
      if (previewRafRef.current !== null) return;
      previewRafRef.current = requestAnimationFrame(flushPreviewFrame);
    },
    [flushPreviewFrame],
  );

  useEffect(() => () => clearPreview(), [clearPreview]);

  useEffect(() => {
    fetchStatus()
      .then((status) => {
        if (status.dominant_hand === "left" || status.dominant_hand === "right") {
          setDominantHand(status.dominant_hand);
        }
        if (status.gesture_active) {
          setIsCameraActive(true);
          setDetectedGesture((prev) => prev || "Waiting for gesture...");
        }
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (isCameraActive && previewUrlRef.current && previewRef.current) {
      previewRef.current.src = previewUrlRef.current;
    }
  }, [isCameraActive, hasPreview]);

  useBackendSocket(
    useCallback(
      (event, data) => {
        if (event === "gesture.started") {
          setIsCameraActive(true);
          setDetectedGesture((prev) => prev || "Waiting for gesture...");
          setError(null);
        }
        if (event === "gesture.detected") {
          const g = String(data.gesture || "");
          if (g) setDetectedGesture(g);
        }
        if (event === "gesture.stopped") {
          setIsCameraActive(false);
          clearPreview();
          setDetectedGesture("");
        }
        if (event === "gesture.error") {
          setError(String(data.message || "Gesture error"));
          setIsCameraActive(false);
          clearPreview();
        }
        if (event === "gesture.dominant_hand") {
          const hand = String(data.hand || "");
          if (hand === "left" || hand === "right") setDominantHand(hand);
        }
      },
      [clearPreview],
    ),
    applyPreviewFrame,
  );

  const toggleDominantHand = async () => {
    const nextHand = dominantHand === "left" ? "right" : "left";
    setError(null);
    try {
      const res = await setGestureDominantHand(nextHand);
      if (res.error) {
        setError(String(res.error));
        return;
      }
      setDominantHand(nextHand);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update dominant hand");
    }
  };

  const startCamera = useCallback(async () => {
    setError(null);
    try {
      const res = await startGesture();
      if (res.error) {
        if (res.error === "gesture_already_running") {
          setIsCameraActive(true);
          setDetectedGesture((prev) => prev || "Waiting for gesture...");
          return;
        }
        setError(String(res.error));
        return;
      }
      setIsCameraActive(true);
      clearPreview();
      setDetectedGesture("Waiting for gesture...");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start gesture");
    }
  }, [clearPreview]);

  const toggleCamera = async () => {
    setError(null);
    if (isCameraActive) {
      try {
        await stopGesture();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to stop gesture");
      }
      setIsCameraActive(false);
      clearPreview();
      setDetectedGesture("");
      return;
    }
    await startCamera();
  };

  useEffect(() => {
    const onAutoStart = () => {
      if (isCameraActive) return;
      void startCamera();
    };
    window.addEventListener(AUTO_START_GESTURE, onAutoStart);
    return () => window.removeEventListener(AUTO_START_GESTURE, onAutoStart);
  }, [isCameraActive, startCamera]);

  const cameraPanel = (
    <motion.div className="bg-card border border-border rounded-lg flex flex-col overflow-hidden p-3 gap-3 flex-1 min-h-0 app-no-drag">
      <motion.div className="relative flex-1 min-h-[120px] bg-muted/50 rounded-lg border border-border overflow-hidden">
        <motion.button
          type="button"
          whileHover={{ scale: 1.03 }}
          whileTap={{ scale: 0.97 }}
          onClick={toggleCamera}
          className={`absolute top-3 right-3 z-10 inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium shadow-sm transition-colors app-no-drag ${
            isCameraActive
              ? "bg-red-500 hover:bg-red-600 text-white"
              : "bg-white hover:bg-white/90 text-black"
          }`}
        >
          {isCameraActive ? (
            <>
              <VideoOff size={14} />
              Stop Camera
            </>
          ) : (
            <>
              <Video size={14} />
              Start Camera
            </>
          )}
        </motion.button>
        {isCameraActive ? (
          <>
            <img
              ref={previewRef}
              alt="Live camera feed"
              className={`absolute inset-0 w-full h-full object-cover ${hasPreview ? "opacity-100" : "opacity-0"}`}
            />
            {!hasPreview && (
              <motion.div className="absolute inset-0 flex flex-col items-center justify-center text-center px-4">
                <motion.div className="w-16 h-16 bg-primary/10 rounded-full flex items-center justify-center mb-3 animate-pulse">
                  <Video size={32} className="text-primary" />
                </motion.div>
                <p className="text-sm text-muted-foreground">Connecting to camera...</p>
              </motion.div>
            )}
          </>
        ) : (
          <motion.div className="absolute inset-0 flex flex-col items-center justify-center text-center px-4">
            <VideoOff size={40} className="text-muted-foreground mb-3" />
            <p className="text-sm text-muted-foreground">Camera Inactive</p>
          </motion.div>
        )}
      </motion.div>

      <motion.div className="shrink-0 h-[4.75rem] rounded-lg border border-border bg-card/50 px-3 py-2.5 flex flex-col justify-center">
        <motion.div className="flex items-center gap-2 mb-1">
          <Hand size={16} className="text-muted-foreground shrink-0" />
          <span className="text-xs text-muted-foreground">Detected</span>
        </motion.div>
        <p className="text-base leading-snug truncate">
          {isCameraActive ? detectedGesture || "Waiting for gesture..." : "—"}
        </p>
      </motion.div>
    </motion.div>
  );

  if (compact) {
    return (
      <motion.div className="h-full flex flex-col min-h-0">
        <div className="flex items-center justify-between gap-2 px-4 py-3 border-b border-border shrink-0 app-drag">
          <div className="flex items-center gap-3 min-w-0">
            <Link
              to="/compact"
              className="w-8 h-8 rounded-lg flex items-center justify-center hover:bg-accent transition-colors app-no-drag"
              aria-label="Back"
            >
              <ArrowLeft size={18} />
            </Link>
            <h1 className="text-lg font-medium truncate">Gesture Control</h1>
          </div>
          <div className="relative shrink-0 app-no-drag">
            <button
              type="button"
              onClick={() => setShowSettings(!showSettings)}
              className="w-8 h-8 bg-card border border-border rounded-lg flex items-center justify-center hover:bg-accent transition-colors"
              aria-label="Settings"
            >
              <Settings size={16} />
            </button>
            <AnimatePresence>
              {showSettings && (
                <motion.div
                  initial={{ opacity: 0, y: -8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  transition={{ duration: 0.2 }}
                  className="absolute right-0 top-10 w-56 bg-card border border-border rounded-lg shadow-lg z-20"
                >
                  <div className="p-3">
                    <label className="text-xs text-muted-foreground mb-2 block">
                      Preferred Dominant Hand
                    </label>
                    <div className="flex items-center justify-between gap-3 px-0.5">
                      <span
                        className={`text-xs w-9 text-center shrink-0 ${dominantHand === "left" ? "text-foreground font-medium" : "text-muted-foreground/40"}`}
                      >
                        Left
                      </span>
                      <button
                        type="button"
                        onClick={toggleDominantHand}
                        className="relative w-12 h-6 rounded-full bg-muted/80 shrink-0 overflow-hidden"
                      >
                        <span
                          className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform duration-200 ${
                            dominantHand === "right" ? "translate-x-6" : "translate-x-0"
                          }`}
                        />
                      </button>
                      <span
                        className={`text-xs w-9 text-center shrink-0 ${dominantHand === "right" ? "text-foreground font-medium" : "text-muted-foreground/40"}`}
                      >
                        Right
                      </span>
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>

        <div className="flex-1 min-h-0 flex flex-col p-3 overflow-hidden app-no-drag">
          {error && <p className="text-sm text-destructive mb-3 shrink-0">{error}</p>}
          {cameraPanel}
        </div>
      </motion.div>
    );
  }

  return (
    <motion.div className="h-full flex flex-col">
      <motion.div className="p-8 border-b border-border">
        <motion.div className="flex items-start justify-between gap-4">
          <motion.div>
            <h1 className="text-3xl font-medium mb-2">Gesture Control</h1>
            <p className="text-muted-foreground">Navigate using hand gestures and camera</p>
          </motion.div>
          <motion.div className="relative shrink-0">
              <motion.button
                type="button"
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
                onClick={() => setShowSettings(!showSettings)}
                className="w-10 h-10 bg-card border border-border rounded-lg flex items-center justify-center hover:bg-accent transition-colors"
                aria-label="Settings"
              >
                <Settings size={20} />
              </motion.button>

              <AnimatePresence>
                {showSettings && (
                  <motion.div
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -10 }}
                    transition={{ duration: 0.2 }}
                    className="absolute right-0 top-12 w-72 bg-card border border-border rounded-lg shadow-lg z-10"
                  >
                    <motion.div className="p-4">
                      <label className="text-sm text-muted-foreground mb-3 block">
                        Preferred Dominant Hand
                      </label>
                      <motion.div className="flex items-center gap-3">
                        <span
                          className={`text-sm ${dominantHand === "left" ? "text-foreground font-medium" : "text-muted-foreground/40"}`}
                        >
                          Left
                        </span>
                        <button
                          type="button"
                          onClick={toggleDominantHand}
                          className="relative w-12 h-6 rounded-full bg-muted/80"
                        >
                          <motion.div
                            className={`absolute top-0.5 w-5 h-5 bg-white rounded-full transition-transform duration-200 ${
                              dominantHand === "right" ? "translate-x-6" : "translate-x-0.5"
                            }`}
                          />
                        </button>
                        <span
                          className={`text-sm ${dominantHand === "right" ? "text-foreground font-medium" : "text-muted-foreground/40"}`}
                        >
                          Right
                        </span>
                      </motion.div>
                    </motion.div>
                  </motion.div>
                )}
              </AnimatePresence>
          </motion.div>
        </motion.div>
      </motion.div>

      <motion.div className="p-8 flex-1 min-h-0">
        {error && <p className="text-sm text-destructive mb-4">{error}</p>}
        <motion.div className="grid grid-cols-1 lg:grid-cols-[1.5fr_1fr] gap-6">
          <motion.div className="bg-card border border-border rounded-lg h-[500px] flex flex-col overflow-hidden p-3 gap-3">
            <motion.div className="relative flex-1 min-h-[320px] bg-muted/50 rounded-lg border border-border overflow-hidden">
              <motion.button
                type="button"
                whileHover={{ scale: 1.03 }}
                whileTap={{ scale: 0.97 }}
                onClick={toggleCamera}
                className={`absolute top-3 right-3 z-10 inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium shadow-sm transition-colors ${
                  isCameraActive
                    ? "bg-red-500 hover:bg-red-600 text-white"
                    : "bg-primary hover:bg-primary/90 text-primary-foreground"
                }`}
              >
                {isCameraActive ? (
                  <>
                    <VideoOff size={14} />
                    Stop Camera
                  </>
                ) : (
                  <>
                    <Video size={14} />
                    Start Camera
                  </>
                )}
              </motion.button>
              {isCameraActive ? (
                <>
                  <img
                    ref={previewRef}
                    alt="Live camera feed"
                    className={`absolute inset-0 w-full h-full object-cover ${hasPreview ? "opacity-100" : "opacity-0"}`}
                  />
                  {!hasPreview && (
                    <motion.div className="absolute inset-0 flex flex-col items-center justify-center text-center px-4">
                      <motion.div className="w-16 h-16 bg-primary/10 rounded-full flex items-center justify-center mb-3 animate-pulse">
                        <Video size={32} className="text-primary" />
                      </motion.div>
                      <p className="text-sm text-muted-foreground">Connecting to camera...</p>
                    </motion.div>
                  )}
                </>
              ) : (
                <motion.div className="absolute inset-0 flex flex-col items-center justify-center text-center px-4">
                  <VideoOff size={40} className="text-muted-foreground mb-3" />
                  <p className="text-sm text-muted-foreground">Camera Inactive</p>
                </motion.div>
              )}
            </motion.div>

            <motion.div className="shrink-0 h-[4.75rem] rounded-lg border border-border bg-card/50 px-3 py-2.5 flex flex-col justify-center">
              <motion.div className="flex items-center gap-2 mb-1">
                <Hand size={16} className="text-muted-foreground shrink-0" />
                <span className="text-xs text-muted-foreground">Detected</span>
              </motion.div>
              <p className="text-base leading-snug truncate">
                {isCameraActive ? detectedGesture || "Waiting for gesture..." : "—"}
              </p>
            </motion.div>
          </motion.div>

          <motion.div className="bg-card border border-border rounded-lg p-4 h-[500px] flex flex-col">
            <h3 className="text-sm font-medium mb-4">Gesture Guide</h3>
            <motion.div className="thin-scrollbar flex-1 overflow-y-auto pr-1 space-y-3 min-h-0">
              {[
                { name: "Palm Open", description: "Neutral action", icon: "✋" },
                { name: "Peace Sign", description: "Move cursor", icon: "✌️" },
                { name: "Index Finger", description: "Right click", icon: "☝️" },
                { name: "Middle Finger", description: "Left click", icon: "🖕" },
                { name: "Fist", description: "Drag and drop", icon: "✊" },
                { name: "Pinch", description: "Adjust volume or brightness", icon: "🤏" },
                { name: "Call Sign", description: "Launch Voice Assistant", icon: "🤙" },
                { name: "Multi Index Finger", description: "Zoom In or Out", icon: "👆👆" },
              ].map((gesture, index) => (
                <motion.div
                  key={index}
                  className="flex items-start gap-3 p-3 bg-muted rounded-lg hover:bg-accent transition-colors"
                >
                  <motion.div
                    className={`${gesture.name === "Multi Index Finger" ? "w-14" : "w-9"} h-9 bg-card rounded-lg flex items-center justify-center text-lg flex-shrink-0`}
                  >
                    {gesture.icon}
                  </motion.div>
                  <motion.div className="flex-1 min-w-0">
                    <h4 className="text-xs font-medium mb-0.5">{gesture.name}</h4>
                    <p className="text-xs text-muted-foreground">{gesture.description}</p>
                  </motion.div>
                </motion.div>
              ))}
            </motion.div>

            <motion.div className="mt-3 p-3 bg-blue-500/10 border border-blue-500/20 rounded-lg shrink-0">
              <p className="text-xs text-blue-400">
                <strong>Tip:</strong> Keep your hand within the camera frame and ensure good lighting for
                best results.
              </p>
            </motion.div>
          </motion.div>
        </motion.div>
      </motion.div>
    </motion.div>
  );
}
