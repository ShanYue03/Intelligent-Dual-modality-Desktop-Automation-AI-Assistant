import { useState, useEffect } from "react";
import { Link } from "react-router";
import { Mic, Hand } from "lucide-react";
import { motion } from "motion/react";
import logoImage from "../../assets/Logo.png";

export function CompactMainPage() {
  const [currentTime, setCurrentTime] = useState(new Date());

  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const formatDate = (date: Date) =>
    date.toLocaleDateString("en-US", {
      weekday: "long",
      year: "numeric",
      month: "long",
      day: "numeric",
    });

  const formatTime = (date: Date) =>
    date.toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });

  const modeButtonClass =
    "flex flex-col items-center justify-center gap-1.5 w-24 h-24 rounded-2xl border border-zinc-700/50 bg-gradient-to-br from-black via-zinc-900 to-zinc-700 hover:brightness-110 transition-all duration-200";

  return (
    <motion.div
      className="h-full flex flex-col px-5 py-3"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.2 }}
    >
      <div className="flex items-center justify-between mb-4 shrink-0 app-drag">
        <h2 className="text-lg font-medium">Hello Lee!</h2>
        <div className="text-right">
          <div className="text-[11px] text-muted-foreground leading-tight">{formatDate(currentTime)}</div>
          <div className="text-sm font-medium tabular-nums">{formatTime(currentTime)}</div>
        </div>
      </div>

      <div className="flex-1 flex flex-col items-center justify-center gap-5 min-h-0">
        <div className="flex flex-col items-center text-center gap-2">
          <img src={logoImage} alt="Friday" className="w-20 h-20 object-contain" />
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Friday</h1>
            <p className="text-sm text-muted-foreground mt-1">Multimodal Assistant</p>
          </div>
        </div>

        <div className="flex items-center justify-center gap-4">
          <Link to="/compact/voice" className={modeButtonClass}>
            <Mic size={22} className="text-foreground" />
            <span className="text-sm font-medium">Voice</span>
          </Link>
          <Link to="/compact/gesture" className={modeButtonClass}>
            <Hand size={22} className="text-foreground" />
            <span className="text-sm font-medium">Gesture</span>
          </Link>
        </div>
      </div>
    </motion.div>
  );
}
