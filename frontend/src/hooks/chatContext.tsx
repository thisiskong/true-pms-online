import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { useChat } from "./useChat";

export interface DeviceContext {
  id: number;
  name: string | null;
}

type Chat = ReturnType<typeof useChat>;

interface ChatCtx extends Chat {
  drawerOpen: boolean;
  setDrawerOpen: (v: boolean) => void;
  device: DeviceContext | null;
  setDevice: (d: DeviceContext | null) => void;
  askAboutDevice: (d: DeviceContext) => void;
}

const Ctx = createContext<ChatCtx | null>(null);

export function ChatProvider({ children }: { children: ReactNode }) {
  const chat = useChat();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [device, setDevice] = useState<DeviceContext | null>(null);

  const askAboutDevice = useCallback((d: DeviceContext) => {
    setDevice(d);
    setDrawerOpen(true);
  }, []);

  const value = useMemo(
    () => ({ ...chat, drawerOpen, setDrawerOpen, device, setDevice, askAboutDevice }),
    [chat, drawerOpen, device, askAboutDevice],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useChatCtx(): ChatCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useChatCtx outside ChatProvider");
  return v;
}
