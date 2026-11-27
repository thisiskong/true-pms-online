# PMS Online prototype — frontend

React 19 + TypeScript + Vite + Tailwind CSS v4, TanStack Query, ECharts, react-markdown.

| Route | Page |
|---|---|
| `/devices` | Device list: KPI strip, search + facet filters (in the URL), server-side sort/paging, CSV export |
| `/devices/:id` | Device dashboard: identity, location/topology, uptime, interface charts, interfaces / recent changes / LLDP neighbors tabs |
| `/chat` | Full-page assistant. The same conversation also lives in the **Ask AI** drawer on every page. |

## Run

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173, proxies /api -> http://localhost:8000 (start the backend first)
npm run build      # -> dist/ ; the backend serves it at http://localhost:8000/
npm run typecheck
```

## Layout

```
src/
  api/          types.ts (mirrors backend models), client.ts (fetch wrapper)
  hooks/        useChat.ts (SSE-over-fetch parser + message state), chatContext.tsx (shared chat + drawer)
  components/   ui.tsx, DataTable.tsx, Layout.tsx, device/*, chat/ChatPanel.tsx
  pages/        DeviceListPage, DeviceDashboard (lazy-loaded with ECharts), ChatPage
```

Chat SSE events from `/api/chat`: `session`, `text`, `tool_start`, `tool_end`, `table`, `notice`, `error`, `done`.
