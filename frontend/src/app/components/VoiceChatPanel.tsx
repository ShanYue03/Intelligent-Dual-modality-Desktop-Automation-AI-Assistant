import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { motion } from "motion/react";
import { fetchVoiceChatHistory } from "../../lib/api";
import logoImage from "../../assets/LogoRounded.png";

export type ChatMessage = {
  id: string;
  role: "user" | "system";
  text: string;
  timestamp: string;
  userStyle: 0 | 1 | 2 | 3;
};

export type VoiceChatHandle = {
  append: (role: "user" | "system", text: string, timestamp?: string) => void;
};

type UserBubbleStyle = 0 | 1 | 2 | 3;

const USER_BUBBLE_CLASS: Record<UserBubbleStyle, string> = {
  0: "bg-[#e0409f] text-white",
  1: "bg-gradient-to-br from-[#e0409f] via-[#a855f7] to-[#4f5bd5] text-white",
  2: "bg-[#4f5bd5] text-white",
  3: "bg-gradient-to-br from-[#4f5bd5] via-[#a855f7] to-[#e0409f] text-white",
};

/** Same greyscale gradient as Main page shortcut cards — all system bubbles use this. */
const SYSTEM_BUBBLE_CLASS =
  "bg-gradient-to-br from-black via-zinc-900 to-zinc-700 text-zinc-100";

function nextUserStyle(messages: ChatMessage[]): UserBubbleStyle {
  const userCount = messages.filter((m) => m.role === "user").length;
  return (userCount % 4) as UserBubbleStyle;
}

function toChatMessage(
  role: "user" | "system",
  text: string,
  timestamp: string,
  userStyle: UserBubbleStyle,
  id?: string,
): ChatMessage {
  return {
    id: id || `${timestamp}-${role}-${text.slice(0, 24)}`,
    role,
    text,
    timestamp,
    userStyle,
  };
}

/** Tight gap between consecutive messages from the same sender; larger when sender changes. */
function messageRowSpacing(index: number, messages: ChatMessage[]): string {
  if (index === 0) return "";
  const prev = messages[index - 1];
  const curr = messages[index];
  return prev.role === curr.role ? "mt-1.5" : "mt-5";
}

function historyToMessages(
  rows: Array<{ role: string; text: string; timestamp: string }>,
): ChatMessage[] {
  const out: ChatMessage[] = [];
  let userIndex = 0;
  for (const row of rows) {
    const role = row.role === "system" ? "system" : "user";
    const style = role === "user" ? ((userIndex++ % 4) as UserBubbleStyle) : 0;
    out.push(toChatMessage(role, row.text, row.timestamp, style));
  }
  return out;
}

export const VoiceChatPanel = forwardRef<VoiceChatHandle, { compact?: boolean }>(function VoiceChatPanel(
  { compact = false },
  ref,
) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchVoiceChatHistory();
        if (cancelled) return;
        setMessages(historyToMessages(data.messages || []));
      } catch {
        if (!cancelled) setMessages([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  const append = useCallback((role: "user" | "system", text: string, timestamp?: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    const ts = timestamp || new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
    setMessages((prev) => {
      const last = prev[prev.length - 1];
      // Skip exact duplicate (e.g. WebSocket + HTTP both delivering the same line).
      if (last && last.role === role && last.text === trimmed) {
        return prev;
      }
      const style = role === "user" ? nextUserStyle(prev) : 0;
      return [...prev, toChatMessage(role, trimmed, ts, style)];
    });
  }, []);

  useImperativeHandle(ref, () => ({ append }), [append]);

  return (
    <div
      className={
        compact
          ? "flex flex-col flex-1 min-h-0 border-[1.5px] border-zinc-300/80 rounded-xl bg-black overflow-hidden app-no-drag"
          : "hidden lg:flex flex-col h-[500px] border-[1.5px] border-zinc-300/80 rounded-xl bg-black overflow-hidden"
      }
    >
      <motion.div className="shrink-0 px-4 py-3 border-b border-border/60">
        <h3 className="text-sm font-medium text-foreground">Chat</h3>
        <p className="text-xs text-muted-foreground mt-0.5">Last 3 days</p>
      </motion.div>

      <div ref={scrollRef} className="thin-scrollbar flex-1 overflow-y-auto overscroll-contain px-3 py-3 min-h-0">
        {loading && (
          <p className="text-xs text-muted-foreground text-center py-8">Loading chat...</p>
        )}
        {!loading && messages.length === 0 && (
          <p className="text-xs text-muted-foreground text-center py-8">
            No messages yet. Start a voice command to chat.
          </p>
        )}
        {messages.map((msg, index) =>
          msg.role === "user" ? (
            <motion.div
              key={msg.id}
              className={`flex justify-end ${messageRowSpacing(index, messages)}`}
            >
              <motion.div
                className={`max-w-[88%] rounded-[22px] px-4 py-2.5 text-sm leading-snug shadow-sm whitespace-pre-line ${USER_BUBBLE_CLASS[msg.userStyle]}`}
              >
                {msg.text}
              </motion.div>
            </motion.div>
          ) : (
            <motion.div
              key={msg.id}
              className={`flex items-end gap-2 justify-start ${messageRowSpacing(index, messages)}`}
            >
              <motion.div className="w-7 h-7 rounded-full overflow-hidden shrink-0 mb-0.5 border border-border/40">
                <img src={logoImage} alt="Friday" className="w-full h-full object-cover" />
              </motion.div>
              <motion.div
                className={`max-w-[calc(100%-2.25rem)] rounded-[22px] px-4 py-2.5 text-sm leading-snug shadow-sm whitespace-pre-line ${SYSTEM_BUBBLE_CLASS}`}
              >
                {msg.text}
              </motion.div>
            </motion.div>
          ),
        )}
      </div>
    </div>
  );
});
