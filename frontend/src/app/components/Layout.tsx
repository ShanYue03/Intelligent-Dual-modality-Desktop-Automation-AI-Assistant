import { Outlet, NavLink, useLocation } from "react-router";
import { useEffect, useState, useCallback, useRef } from "react";
import { fetchStatus } from "../../lib/api";
import { useBackendSocket } from "../../hooks/useBackendSocket";
import { enterCompactMode, isCompactWindow } from "../../lib/desktop";
import { useModuleSwitchHandler } from "../../hooks/useModuleSwitchListener";
import { LayoutDashboard, Home, Mic, Hand } from "lucide-react";
import { motion, AnimatePresence } from "motion/react";
import { FridayIcon } from "./FridayIcon";

export function Layout() {
  const location = useLocation();
  const [active, setActive] = useState(false);
  const handleModuleSwitch = useModuleSwitchHandler();

  useEffect(() => {
    const load = async () => {
      try {
        await fetchStatus();
        setActive(true);
      } catch {
        setActive(false);
      }
    };
    load();
    const id = setInterval(load, 2000);
    return () => clearInterval(id);
  }, []);

  const autoCompactForAutomationRef = useRef(false);

  useBackendSocket(
    useCallback(
      (event, data) => {
        handleModuleSwitch(event, data);
        if (event !== "voice.automation") return;
        const active = Boolean(data.active);
        if (!active) {
          autoCompactForAutomationRef.current = false;
          return;
        }
        if (isCompactWindow() || autoCompactForAutomationRef.current) return;
        autoCompactForAutomationRef.current = true;
        void enterCompactMode({ animate: true, routePath: "/compact/voice" });
      },
      [handleModuleSwitch],
    ),
  );

  return (
    <div className="dark min-h-screen bg-background text-foreground flex">
      {/* Sidebar */}
      <aside className="w-64 bg-card border-r border-border flex flex-col">
        <div className="p-6 border-b border-border">
          <div className="flex items-center gap-3">
            <FridayIcon />
            <h1 className="text-xl font-medium">Friday</h1>
          </div>
          <p className="text-sm text-muted-foreground mt-1">Voice & Gesture Assistant</p>
        </div>

        <nav className="flex-1 p-4">
          <ul className="space-y-2">
            <li>
              <NavLink
                to="/"
                end
                className={({ isActive }) =>
                  `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
                    isActive
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                  }`
                }
              >
                <Home size={20} />
                <span>Main</span>
              </NavLink>
            </li>
            <li>
              <NavLink
                to="/dashboard"
                className={({ isActive }) =>
                  `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
                    isActive
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                  }`
                }
              >
                <LayoutDashboard size={20} />
                <span>Dashboard</span>
              </NavLink>
            </li>
            <li>
              <NavLink
                to="/voice"
                className={({ isActive }) =>
                  `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
                    isActive
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                  }`
                }
              >
                <Mic size={20} />
                <span>Voice Assistant</span>
              </NavLink>
            </li>
            <li>
              <NavLink
                to="/gesture"
                className={({ isActive }) =>
                  `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
                    isActive
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                  }`
                }
              >
                <Hand size={20} />
                <span>Gesture Control</span>
              </NavLink>
            </li>
          </ul>
        </nav>

        <div className="p-4 border-t border-border">
          <div className="px-3 py-2 bg-muted rounded-lg">
            <p className="text-xs text-muted-foreground">Status</p>
            <div className="flex items-center gap-2 mt-0.5">
              <div className={`w-1.5 h-1.5 rounded-full ${active ? "bg-green-500" : "bg-muted-foreground"}`}></div>
              <span className="text-xs">{active ? "Active" : "Inactive"}</span>
            </div>
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 overflow-auto bg-background">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={location.pathname}
            initial={{ opacity: 0, x: 15 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -15 }}
            transition={{
              duration: 0.25,
              ease: [0.4, 0, 0.2, 1]
            }}
          >
            <Outlet />
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}
