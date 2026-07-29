import { Mic, Hand, LayoutDashboard, ArrowRight, Pencil } from "lucide-react";
import { Link } from "react-router";
import { useState, useEffect, useRef } from "react";
import { motion } from "motion/react";
import { fetchUserName, updateUserName } from "../../lib/api";

export function MainPage() {
  const [currentTime, setCurrentTime] = useState(new Date());
  const [userName, setUserName] = useState("Lee");
  const [editingName, setEditingName] = useState(false);
  const [draftName, setDraftName] = useState("");
  const nameInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    fetchUserName()
      .then(setUserName)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (editingName) {
      nameInputRef.current?.focus();
      nameInputRef.current?.select();
    }
  }, [editingName]);

  const startEditingName = () => {
    setDraftName(userName);
    setEditingName(true);
  };

  const cancelEditingName = () => {
    setEditingName(false);
    setDraftName("");
  };

  const saveUserName = async () => {
    const trimmed = draftName.trim();
    if (!trimmed) {
      cancelEditingName();
      return;
    }
    if (trimmed === userName) {
      cancelEditingName();
      return;
    }
    try {
      const updated = await updateUserName(trimmed);
      setUserName(updated.name);
    } catch {
      /* keep previous name */
    }
    cancelEditingName();
  };

  const handleNameKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      void saveUserName();
    } else if (event.key === "Escape") {
      event.preventDefault();
      cancelEditingName();
    }
  };

  const formatDate = (date: Date) => {
    return date.toLocaleDateString("en-US", {
      weekday: "long",
      year: "numeric",
      month: "long",
      day: "numeric",
    });
  };

  const formatTime = (date: Date) => {
    return date.toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  };

  const shortcutCardClass =
    "block rounded-xl border border-zinc-700/50 p-6 bg-gradient-to-br from-black via-zinc-900 to-zinc-700 transition-all duration-200 group hover:brightness-105 hover:border-zinc-600/60";

  return (
    <div className="h-full flex flex-col p-8">
      <motion.div
        className="flex items-center justify-between mb-8"
        initial={{ opacity: 0, y: -6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
      >
        <motion.div
          className="flex items-center gap-2"
          initial={{ opacity: 0, x: -8 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.05, duration: 0.3 }}
        >
          {editingName ? (
            <h2 className="text-2xl font-medium flex items-center gap-1">
              <span>Hi there,</span>
              <input
                ref={nameInputRef}
                value={draftName}
                onChange={(event) => setDraftName(event.target.value)}
                onBlur={() => void saveUserName()}
                onKeyDown={handleNameKeyDown}
                className="bg-transparent border-b border-primary/60 outline-none min-w-[4ch] max-w-[20ch] text-2xl font-medium"
                aria-label="Edit your name"
              />
              <span>!</span>
            </h2>
          ) : (
            <>
              <h2 className="text-2xl font-medium">Hi there, {userName}!</h2>
              <button
                type="button"
                onClick={startEditingName}
                className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-white/5 transition-colors"
                aria-label="Edit name"
              >
                <Pencil size={16} />
              </button>
            </>
          )}
        </motion.div>
        <motion.div
          className="text-right"
          initial={{ opacity: 0, x: 8 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.05, duration: 0.3 }}
        >
          <div className="text-sm text-muted-foreground">{formatDate(currentTime)}</div>
          <div className="text-lg font-medium tabular-nums">{formatTime(currentTime)}</div>
        </motion.div>
      </motion.div>

      <div className="flex-1 flex flex-col items-center justify-center pt-12">
        <div className="max-w-4xl w-full translate-y-[10vh]">
          <div className="text-center mb-12">
            <h1 className="text-4xl font-medium mb-4">Voice & Gesture Assistant</h1>
            <p className="text-muted-foreground text-lg">
              Control your desktop with advanced voice commands and gesture recognition
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <motion.div whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }} transition={{ duration: 0.2 }}>
              <Link
                to="/dashboard"
                className={shortcutCardClass}
              >
                <div className="w-12 h-12 bg-white/10 rounded-lg flex items-center justify-center mb-4 group-hover:bg-white/15 transition-colors">
                  <LayoutDashboard size={24} className="text-primary" />
                </div>
                <h3 className="text-lg font-medium mb-2">Dashboard</h3>
                <p className="text-muted-foreground text-sm mb-4">View analytics and system overview</p>
                <div className="flex items-center text-sm text-primary">
                  <span>Open</span>
                  <ArrowRight size={16} className="ml-2" />
                </div>
              </Link>
            </motion.div>

            <motion.div whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }} transition={{ duration: 0.2 }}>
              <Link
                to="/voice"
                className={shortcutCardClass}
              >
                <div className="w-12 h-12 bg-white/10 rounded-lg flex items-center justify-center mb-4 group-hover:bg-white/15 transition-colors">
                  <Mic size={24} className="text-primary" />
                </div>
                <h3 className="text-lg font-medium mb-2">Voice Assistant</h3>
                <p className="text-muted-foreground text-sm mb-4">Control with voice commands</p>
                <motion.div className="flex items-center text-sm text-primary" whileHover={{ x: 4 }}>
                  <span>Open</span>
                  <ArrowRight size={16} className="ml-2" />
                </motion.div>
              </Link>
            </motion.div>

            <motion.div whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }} transition={{ duration: 0.2 }}>
              <Link
                to="/gesture"
                className={shortcutCardClass}
              >
                <motion.div
                  className="w-12 h-12 bg-white/10 rounded-lg flex items-center justify-center mb-4 group-hover:bg-white/15 transition-colors"
                  whileHover={{ rotate: [0, 8, -8, 0] }}
                  transition={{ duration: 0.45 }}
                >
                  <Hand size={24} className="text-primary" />
                </motion.div>
                <h3 className="text-lg font-medium mb-2">Gesture Control</h3>
                <p className="text-muted-foreground text-sm mb-4">Navigate using hand gestures</p>
                <motion.div className="flex items-center text-sm text-primary" whileHover={{ x: 4 }}>
                  <span>Open</span>
                  <ArrowRight size={16} className="ml-2" />
                </motion.div>
              </Link>
            </motion.div>
          </div>
        </div>
      </div>
    </div>
  );
}
