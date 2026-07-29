import { Outlet } from "react-router";
import { Home } from "lucide-react";
import { motion } from "motion/react";
import { exitCompactMode } from "../../lib/desktop";
import { useModuleSwitchHandler } from "../../hooks/useModuleSwitchListener";
import { useBackendSocket } from "../../hooks/useBackendSocket";

export function CompactShell() {
  const handleModuleSwitch = useModuleSwitchHandler();
  useBackendSocket(handleModuleSwitch);

  return (
    <motion.div
      className="dark h-screen w-full bg-background text-foreground flex flex-col overflow-hidden border border-zinc-600/60 box-border"
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ type: "spring", stiffness: 480, damping: 34, mass: 0.8 }}
    >
      <motion.div className="shrink-0 flex items-center justify-end h-8 px-2 bg-background/80 border-b border-border/40 app-drag">
        <button
          type="button"
          title="Restore maximized window"
          onClick={() => exitCompactMode()}
          className="w-7 h-7 rounded-md flex items-center justify-center text-foreground hover:bg-white/10 transition-colors app-no-drag"
        >
          <Home size={14} />
        </button>
      </motion.div>
      <motion.div className="flex-1 min-h-0 overflow-hidden app-no-drag">
        <Outlet />
      </motion.div>
    </motion.div>
  );
}
