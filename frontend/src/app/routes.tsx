import { createHashRouter } from "react-router";
import { Layout } from "./components/Layout";
import { MainPage } from "./components/MainPage";
import { Dashboard } from "./components/Dashboard";
import { VoiceAssistant } from "./components/VoiceAssistant";
import { GestureControl } from "./components/GestureControl";
import { CompactShell } from "./components/CompactShell";
import { CompactMainPage } from "./components/CompactMainPage";

function CompactVoiceRoute() {
  return <VoiceAssistant compact />;
}

function CompactGestureRoute() {
  return <GestureControl compact />;
}

export const router = createHashRouter([
  {
    path: "/",
    Component: Layout,
    children: [
      { index: true, Component: MainPage },
      { path: "dashboard", Component: Dashboard },
      { path: "voice", Component: VoiceAssistant },
      { path: "gesture", Component: GestureControl },
    ],
  },
  {
    path: "/compact",
    Component: CompactShell,
    children: [
      { index: true, Component: CompactMainPage },
      { path: "voice", Component: CompactVoiceRoute },
      { path: "gesture", Component: CompactGestureRoute },
    ],
  },
]);
