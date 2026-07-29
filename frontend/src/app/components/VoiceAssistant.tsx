import { useState, useCallback, useRef, useEffect } from "react";
import { Link } from "react-router";
import { startVoice } from "../../lib/api";
import { useBackendSocket } from "../../hooks/useBackendSocket";
import { AUTO_START_VOICE } from "../../hooks/useModuleSwitchListener";
import { Mic, Settings, ArrowLeft } from "lucide-react";
import { motion, AnimatePresence } from "motion/react";
import { VoiceChatPanel, type VoiceChatHandle } from "./VoiceChatPanel";

type VoicePhase =
  | "idle"
  | "preparing"
  | "recording"
  | "processing"
  | "transcribing"
  | "speaking"
  | "automation_listening";

export function VoiceAssistant({ compact = false }: { compact?: boolean }) {
  const [phase, setPhase] = useState<VoicePhase>("idle");
  const [sessionBusy, setSessionBusy] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);
  const [transcript, setTranscript] = useState("");
  const [showSettings, setShowSettings] = useState(false);
  const [language, setLanguage] = useState<"EN" | "CN">("EN");
  const [error, setError] = useState<string | null>(null);
  const [automationLoopActive, setAutomationLoopActive] = useState(false);
  const phaseRef = useRef<VoicePhase>("idle");
  const chatRef = useRef<VoiceChatHandle>(null);

  const isRecording = phase === "recording";
  const isPreparing = phase === "preparing";
  const micActive =
    sessionBusy ||
    isPreparing ||
    isRecording ||
    phase === "processing" ||
    phase === "transcribing" ||
    phase === "speaking" ||
    phase === "automation_listening" ||
    automationLoopActive;

  useEffect(() => {
    phaseRef.current = phase;
  }, [phase]);

  useBackendSocket(
    useCallback((event, data) => {
      if (event === "voice.level") {
        if (phaseRef.current !== "recording") return;
        const speaking = Boolean(data.speaking);
        const level = Number(data.level) || 0;
        setIsSpeaking(speaking);
        setAudioLevel(level);
      }
      if (event === "voice.status") {
        const next = String(data.phase || "");
        const allowed: VoicePhase[] = [
          "idle",
          "preparing",
          "recording",
          "processing",
          "transcribing",
          "speaking",
          "automation_listening",
        ];
        if (allowed.includes(next as VoicePhase)) {
          setPhase(next as VoicePhase);
        }
        if (next !== "recording") {
          setIsSpeaking(false);
          setAudioLevel(0);
        }
      }
      if (event === "voice.transcript") {
        const original = String(data.original || "");
        const english = String(data.english || "");
        if (original) setTranscript(original);
        else if (english) setTranscript(english);
      }
      if (event === "voice.chat") {
        const role = data.role === "system" ? "system" : "user";
        const text = String(data.text || "");
        const ts = String(data.timestamp || "");
        if (text) chatRef.current?.append(role, text, ts || undefined);
      }
      if (event === "voice.automation") {
        setAutomationLoopActive(Boolean(data.active));
      }
    }, []),
  );

  const toggleListening = async () => {
    if (sessionBusy) return;
    setError(null);
    setTranscript("");
    setIsSpeaking(false);
    setAudioLevel(0);
    setAutomationLoopActive(false);
    setSessionBusy(true);
    setPhase("preparing");
    try {
      const result = await startVoice(language, 5);
      if (result.transcript_original) {
        setTranscript(String(result.transcript_original));
      }
      if (result.error && !result.transcript_original) {
        setError(String(result.error));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Voice request failed");
    } finally {
      setIsSpeaking(false);
      setAudioLevel(0);
      setSessionBusy(false);
      setAutomationLoopActive(false);
      setPhase("idle");
    }
  };

  useEffect(() => {
    const onAutoStart = () => {
      if (sessionBusy) return;
      void toggleListening();
    };
    window.addEventListener(AUTO_START_VOICE, onAutoStart);
    return () => window.removeEventListener(AUTO_START_VOICE, onAutoStart);
  }, [sessionBusy]);

  const statusLabel = (() => {
    if (isPreparing) return "Just a sec";
    if (isRecording) return "Listening";
    if (phase === "transcribing") return "Transcribing...";
    if (phase === "processing") return "Processing...";
    if (phase === "speaking") return "Speaking response...";
    if (phase === "automation_listening" || automationLoopActive) {
      return "Automation — listening...";
    }
    return "Tap mic to start";
  })();

  const micPulseScale =
    isRecording && isSpeaking ? 1 + Math.min(audioLevel * 0.35, 0.18) : 1;

  const commandsEN = {
    left: ["Launch Youtube", "Go to Google News", "Open WhatsApp", "Send Message"],
    right: ["Take Screenshot", "Open Downloads", "Play Music", "Stop Video"],
  };

  const commandsCN = {
    left: ["打开油管", "打开谷歌新闻", "开启WhatsApp", "发送消息"],
    right: ["截图", "打开下载", "播放音乐", "暂停影片"],
  };

  const currentCommands = language === "EN" ? commandsEN : commandsCN;

  const transcriptDisplay =
    transcript ||
    (phase === "transcribing"
      ? "Transcribing your speech..."
      : "Your words will appear here after you speak.");

  const micButton = (
    <motion.div className="relative w-16 h-16 flex items-center justify-center shrink-0 app-no-drag">
      {isRecording && isSpeaking && (
        <>
          {[0, 1, 2].map((i) => (
            <motion.span
              key={i}
              className="absolute inset-0 rounded-full border-2 border-white/50"
              initial={{ scale: 1, opacity: 0.55 }}
              animate={{ scale: 2.1, opacity: 0 }}
              transition={{
                duration: 1.4,
                repeat: Infinity,
                delay: i * 0.45,
                ease: "easeOut",
              }}
            />
          ))}
        </>
      )}
      <motion.button
        type="button"
        onClick={toggleListening}
        disabled={sessionBusy}
        animate={{
          scale:
            isRecording && isSpeaking ? [micPulseScale, micPulseScale * 1.07, micPulseScale] : 1,
        }}
        transition={
          isRecording && isSpeaking
            ? {
                scale: {
                  duration: 0.22,
                  repeat: Infinity,
                  repeatType: "reverse",
                  ease: "easeInOut",
                },
              }
            : { duration: 0.2 }
        }
        className={`relative z-10 w-16 h-16 rounded-full flex items-center justify-center shadow-md transition-colors app-no-drag ${
          micActive
            ? "bg-white text-black cursor-default"
            : "bg-primary hover:bg-primary/90 text-primary-foreground"
        }`}
      >
        <Mic size={28} className={micActive ? "text-black" : "text-primary-foreground"} />
      </motion.button>
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
            <h1 className="text-lg font-medium truncate">Voice Assistant</h1>
          </div>
          <motion.div className="relative shrink-0 app-no-drag">
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
                    <label className="text-xs text-muted-foreground mb-2 block">Language</label>
                    <div className="flex items-center justify-between gap-3 px-0.5">
                      <span
                        className={`text-xs w-7 text-center shrink-0 ${language === "EN" ? "text-foreground font-medium" : "text-muted-foreground/40"}`}
                      >
                        EN
                      </span>
                      <button
                        type="button"
                        onClick={() => setLanguage(language === "EN" ? "CN" : "EN")}
                        disabled={sessionBusy}
                        className="relative w-12 h-6 rounded-full bg-muted/80 shrink-0 overflow-hidden disabled:opacity-50"
                      >
                        <span
                          className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform duration-200 ${
                            language === "CN" ? "translate-x-6" : "translate-x-0"
                          }`}
                        />
                      </button>
                      <span
                        className={`text-xs w-7 text-center shrink-0 ${language === "CN" ? "text-foreground font-medium" : "text-muted-foreground/40"}`}
                      >
                        CN
                      </span>
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        </div>

        <motion.div className="flex-1 min-h-0 flex flex-col gap-2 p-3 overflow-hidden app-no-drag">
          <motion.div className="shrink-0 border border-border rounded-xl bg-card/30 p-3 h-[9.5rem] overflow-hidden">
            <motion.div className="flex gap-3 h-[6.5rem]">
              <motion.div className="w-[4.75rem] shrink-0 flex flex-col items-center">
                <div className="h-16 w-16 shrink-0 flex items-center justify-center overflow-visible">
                  {micButton}
                </div>
                <p className="mt-1.5 text-[10px] text-center text-muted-foreground w-full h-8 leading-[14px] line-clamp-2 overflow-hidden">
                  {statusLabel}
                </p>
              </motion.div>
              <motion.div className="flex-1 min-w-0 h-full bg-card border border-border rounded-lg p-3 flex flex-col overflow-hidden">
                <span className="text-xs text-primary/90 mb-1 font-medium shrink-0">Transcript</span>
                <p
                  className={`text-sm leading-snug flex-1 overflow-hidden line-clamp-4 ${
                    transcript ? "text-foreground" : "text-muted-foreground"
                  }`}
                >
                  {transcriptDisplay}
                </p>
              </motion.div>
            </motion.div>
            <p
              className={`text-xs mt-2 h-4 leading-4 truncate ${error ? "text-destructive" : "invisible"}`}
            >
              {error || "\u00A0"}
            </p>
          </motion.div>

          <VoiceChatPanel ref={chatRef} compact />
        </motion.div>
      </motion.div>
    );
  }

  return (
    <motion.div className="h-full flex flex-col">
      <motion.div className="p-8 border-b border-border shrink-0">
        <motion.div className="flex items-center justify-between">
          <motion.div>
            <h1 className="text-3xl font-medium mb-2">Voice Assistant</h1>
            <p className="text-muted-foreground">Control your system with voice commands</p>
          </motion.div>
          <motion.div className="relative">
            <motion.button
              type="button"
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
              onClick={() => setShowSettings(!showSettings)}
              className="w-10 h-10 bg-card border border-border rounded-lg flex items-center justify-center hover:bg-accent transition-colors"
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
                    <label className="text-sm text-muted-foreground mb-3 block">Language</label>
                    <motion.div className="flex items-center gap-3">
                      <span
                        className={`text-sm ${language === "EN" ? "text-foreground font-medium" : "text-muted-foreground/40"}`}
                      >
                        EN
                      </span>
                      <button
                        type="button"
                        onClick={() => setLanguage(language === "EN" ? "CN" : "EN")}
                        disabled={sessionBusy}
                        className="relative w-12 h-6 rounded-full bg-muted/80"
                      >
                        <motion.div
                          className={`absolute top-0.5 w-5 h-5 bg-white rounded-full transition-transform duration-200 ${
                            language === "CN" ? "translate-x-6" : "translate-x-0.5"
                          }`}
                        />
                      </button>
                      <span
                        className={`text-sm ${language === "CN" ? "text-foreground font-medium" : "text-muted-foreground/40"}`}
                      >
                        CN
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
        <motion.div className="grid grid-cols-1 lg:grid-cols-[7fr_3fr] gap-6">
          {/* Left panel — ~70% width, same height as Gesture Control panels */}
          <motion.div className="flex flex-col gap-4 h-[500px] border border-border rounded-xl bg-card/30 p-5 lg:p-6 overflow-hidden">
            <motion.div className="flex gap-5 items-stretch shrink-0">
              <motion.div className="shrink-0 flex flex-col items-center gap-2 justify-center">
                <motion.div className="relative w-24 h-24 flex items-center justify-center">
                  {isRecording && isSpeaking && (
                    <>
                      {[0, 1, 2].map((i) => (
                        <motion.span
                          key={i}
                          className="absolute inset-0 rounded-full border-2 border-white/50"
                          initial={{ scale: 1, opacity: 0.55 }}
                          animate={{ scale: 2.1, opacity: 0 }}
                          transition={{
                            duration: 1.4,
                            repeat: Infinity,
                            delay: i * 0.45,
                            ease: "easeOut",
                          }}
                        />
                      ))}
                    </>
                  )}

                  <motion.button
                    type="button"
                    onClick={toggleListening}
                    disabled={sessionBusy}
                    animate={{
                      scale:
                        isRecording && isSpeaking
                          ? [micPulseScale, micPulseScale * 1.07, micPulseScale]
                          : 1,
                    }}
                    transition={
                      isRecording && isSpeaking
                        ? {
                            scale: {
                              duration: 0.22,
                              repeat: Infinity,
                              repeatType: "reverse",
                              ease: "easeInOut",
                            },
                          }
                        : { duration: 0.2 }
                    }
                    className={`relative z-10 w-24 h-24 rounded-full flex items-center justify-center shadow-md transition-colors ${
                      micActive
                        ? "bg-white text-black cursor-default"
                        : "bg-primary hover:bg-primary/90 text-primary-foreground"
                    }`}
                  >
                    <Mic size={36} className={micActive ? "text-black" : "text-primary-foreground"} />
                  </motion.button>
                </motion.div>
                <p className="text-xs text-center text-muted-foreground max-w-[5.5rem] leading-tight">
                  {statusLabel}
                </p>
              </motion.div>

              <motion.div className="flex-1 min-w-0 bg-card border border-border rounded-lg p-4 flex flex-col min-h-[5.5rem]">
                <span className="text-sm text-muted-foreground mb-2">Transcript</span>
                <p
                  className={`text-sm leading-relaxed flex-1 ${
                    transcript ? "text-foreground" : "text-muted-foreground"
                  }`}
                >
                  {transcriptDisplay}
                </p>
              </motion.div>
            </motion.div>

            {error && <p className="text-sm text-destructive -mt-2 shrink-0">{error}</p>}

            <motion.div className="bg-card border border-border rounded-lg p-4 flex-1 flex flex-col min-h-0 overflow-hidden">
              <h3 className="text-sm font-medium mb-3 shrink-0">Available Commands</h3>
              <motion.div className="thin-scrollbar grid grid-cols-2 gap-2 flex-1 overflow-y-auto pr-1 content-start">
                <motion.div className="space-y-2">
                  {currentCommands.left.map((command, index) => (
                    <motion.div
                      key={index}
                      className="px-4 py-2 bg-muted rounded-lg text-sm hover:bg-accent transition-colors cursor-pointer"
                    >
                      {command}
                    </motion.div>
                  ))}
                </motion.div>
                <motion.div className="space-y-2">
                  {currentCommands.right.map((command, index) => (
                    <motion.div
                      key={index}
                      className="px-4 py-2 bg-muted rounded-lg text-sm hover:bg-accent transition-colors cursor-pointer"
                    >
                      {command}
                    </motion.div>
                  ))}
                </motion.div>
              </motion.div>
            </motion.div>

            <motion.div className="grid grid-cols-2 gap-3 shrink-0">
              <motion.div className="bg-card border border-border rounded-lg px-4 py-3">
                <motion.div className="flex items-center justify-between">
                  <span className="text-sm">Language</span>
                  <span className="text-sm text-muted-foreground">
                    {language === "EN" ? "English (US)" : "Chinese"}
                  </span>
                </motion.div>
              </motion.div>
              <motion.div className="bg-card border border-border rounded-lg px-4 py-3">
                <motion.div className="flex items-center justify-between">
                  <span className="text-sm">Sensitivity</span>
                  <span className="text-sm text-muted-foreground">High</span>
                </motion.div>
              </motion.div>
            </motion.div>
          </motion.div>

          <VoiceChatPanel ref={chatRef} />
        </motion.div>
      </motion.div>
    </motion.div>
  );
}
