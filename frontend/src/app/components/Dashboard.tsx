import { Activity, Mic, Hand, TrendingUp, Clock, CheckCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { fetchDashboard, formatRelativeTime, type DashboardData } from "../../lib/api";

export function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      try {
        setData(await fetchDashboard());
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load dashboard");
      }
    };
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, []);

  const voiceCount = data?.voice_commands ?? 0;
  const gestureCount = data?.gestures_detected ?? 0;
  const successful = data?.successful_actions ?? 0;
  const responseMs = data?.response_time_ms;
  const recent = data?.recent_activity ?? [];
  const system = data?.system_status;

  const statusLabel = (percent: number | undefined) => {
    if (percent === undefined) return "—";
    if (percent >= 100) return "Active";
    return `${Math.round(percent)}%`;
  };

  const statusLabelClass = (percent: number | undefined) => {
    if (percent === undefined) return "text-muted-foreground";
    if (percent >= 100) return "text-green-500";
    if (percent >= 80) return "text-yellow-500";
    return "text-destructive";
  };

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-3xl font-medium mb-2">Dashboard</h1>
        <p className="text-muted-foreground">Monitor your assistant&apos;s performance and activity</p>
        {error && <p className="text-sm text-destructive mt-2">{error}</p>}
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <div className="bg-card border border-border rounded-lg p-6">
          <div className="flex items-center justify-between mb-4">
            <div className="w-10 h-10 bg-blue-500/10 rounded-lg flex items-center justify-center">
              <Mic size={20} className="text-blue-500" />
            </div>
            <TrendingUp size={16} className="text-green-500" />
          </div>
          <div className="text-2xl font-medium mb-1">{voiceCount.toLocaleString()}</div>
          <div className="text-muted-foreground text-sm">Voice Commands</div>
        </div>

        <div className="bg-card border border-border rounded-lg p-6">
          <div className="flex items-center justify-between mb-4">
            <div className="w-10 h-10 bg-purple-500/10 rounded-lg flex items-center justify-center">
              <Hand size={20} className="text-purple-500" />
            </div>
            <TrendingUp size={16} className="text-green-500" />
          </div>
          <div className="text-2xl font-medium mb-1">{gestureCount.toLocaleString()}</div>
          <div className="text-muted-foreground text-sm">Gestures Detected</div>
        </div>

        <div className="bg-card border border-border rounded-lg p-6">
          <div className="flex items-center justify-between mb-4">
            <div className="w-10 h-10 bg-green-500/10 rounded-lg flex items-center justify-center">
              <CheckCircle size={20} className="text-green-500" />
            </div>
            <div className="text-green-500 text-sm">
              {successful > 0
                ? `${Math.round((successful / Math.max(voiceCount + gestureCount, 1)) * 100)}%`
                : "—"}
            </div>
          </div>
          <div className="text-2xl font-medium mb-1">{successful.toLocaleString()}</div>
          <div className="text-muted-foreground text-sm">Successful Actions</div>
        </div>

        <div className="bg-card border border-border rounded-lg p-6">
          <div className="flex items-center justify-between mb-4">
            <div className="w-10 h-10 bg-orange-500/10 rounded-lg flex items-center justify-center">
              <Clock size={20} className="text-orange-500" />
            </div>
            <div className="text-sm text-muted-foreground">avg</div>
          </div>
          <div className="text-2xl font-medium mb-1">
            {responseMs != null ? `${responseMs}ms` : "—"}
          </div>
          <div className="text-muted-foreground text-sm">Response Time</div>
        </div>
      </div>

      {/* Activity Section */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-card border border-border rounded-lg p-6">
          <div className="flex items-center gap-3 mb-6">
            <Activity size={20} />
            <h2 className="text-lg font-medium">Recent Activity</h2>
          </div>
          <div className="thin-scrollbar max-h-[17.5rem] overflow-y-auto pr-1">
            {recent.length === 0 ? (
              <p className="text-sm text-muted-foreground">No activity logged yet.</p>
            ) : (
              <div className="space-y-0">
                {recent.map((item, index) => (
                  <div
                    key={`${item.time}-${index}`}
                    className="flex items-start gap-3 py-3.5 border-b border-border last:border-0"
                  >
                    <div
                      className={`w-2 h-2 rounded-full mt-2 shrink-0 ${
                        item.type === "voice" ? "bg-blue-500" : "bg-purple-500"
                      }`}
                    />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm leading-snug">{item.action}</p>
                      <p className="text-xs text-muted-foreground mt-1">
                        {formatRelativeTime(item.time)}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="bg-card border border-border rounded-lg p-6">
          <h2 className="text-lg font-medium mb-6">System Status</h2>
          <div className="space-y-6">
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm">Voice Recognition</span>
                <span
                  className={`text-sm ${statusLabelClass(system?.voice_recognition_percent)}`}
                >
                  {statusLabel(system?.voice_recognition_percent)}
                </span>
              </div>
              <div className="h-2 bg-muted rounded-full overflow-hidden">
                <div
                  className="h-full bg-green-500 transition-all duration-300"
                  style={{ width: `${system?.voice_recognition_percent ?? 0}%` }}
                />
              </div>
            </div>
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm">Gesture Detection</span>
                <span
                  className={`text-sm ${statusLabelClass(system?.gesture_detection_percent)}`}
                >
                  {statusLabel(system?.gesture_detection_percent)}
                </span>
              </div>
              <div className="h-2 bg-muted rounded-full overflow-hidden">
                <div
                  className="h-full bg-purple-500 transition-all duration-300"
                  style={{ width: `${system?.gesture_detection_percent ?? 0}%` }}
                />
              </div>
            </div>
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm">CPU Utilization</span>
                <span className="text-sm text-muted-foreground">
                  {system?.cpu_utilization_percent ?? 0}%
                </span>
              </div>
              <div className="h-2 bg-muted rounded-full overflow-hidden">
                <div
                  className="h-full bg-blue-500 transition-all duration-300"
                  style={{ width: `${system?.cpu_utilization_percent ?? 0}%` }}
                />
              </div>
            </div>
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm">Memory Usage</span>
                <span className="text-sm text-muted-foreground">
                  {system?.memory_usage_percent ?? 0}%
                </span>
              </div>
              <div className="h-2 bg-muted rounded-full overflow-hidden">
                <div
                  className="h-full bg-orange-500 transition-all duration-300"
                  style={{ width: `${system?.memory_usage_percent ?? 0}%` }}
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
