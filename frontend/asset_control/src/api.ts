import {io} from "socket.io-client";
import type {
  ControlSnapshot,
  RosterLocomotive,
  SerialDevice,
  SessionSnapshot,
  StationaryAsset,
} from "./types";

// Start with Engine.IO polling and let Socket.IO upgrade to WebSocket.  This is
// more reliable on mobile Safari and still uses WebSocket for steady-state
// command traffic once the upgrade succeeds.
const socket = io({autoConnect: false});
let clientSequence = 0;

function commandId(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();

  // randomUUID is restricted to secure contexts by some Safari versions. MTOS
  // is intentionally served over HTTP on the private layout LAN, while
  // getRandomValues remains available there.
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function emitAck<T>(event: string, payload?: unknown): Promise<T> {
  return new Promise((resolve, reject) => {
    socket.timeout(8000).emit(event, payload, (error: Error | null, value: T & {error?: string}) => {
      if (error) reject(new Error("HMI response timed out"));
      else if (value?.error) reject(new Error(value.error));
      else resolve(value);
    });
  });
}

function connect(): Promise<ControlSnapshot> {
  if (socket.connected) return emitAck("control.snapshot.request");
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error("HMI connection timed out")), 4000);
    socket.once("control.snapshot", (snapshot: ControlSnapshot) => {
      window.clearTimeout(timer);
      resolve(snapshot);
    });
    socket.once("connect_error", (error) => {
      window.clearTimeout(timer);
      reject(error);
    });
    socket.connect();
  });
}

async function command(operation: string, payload: Record<string, unknown>) {
  await connect();
  const value = await emitAck<{accepted: boolean; error?: string}>("control.command", {
    command_id: commandId(),
    client_seq: clientSequence++,
    operation,
    payload,
  });
  if (!value.accepted) throw new Error(value.error ?? "Command rejected");
  return value;
}

export const api = {
  session: async (): Promise<SessionSnapshot> => ({...(await connect()), csrf: ""}),
  snapshot: () => emitAck<ControlSnapshot>("control.snapshot.request"),
  locomotives: () => emitAck<{items: RosterLocomotive[]}>("roster.request"),
  devices: () => emitAck<{items: SerialDevice[]}>("devices.request"),
  stationary: () => emitAck<{items: StationaryAsset[]}>("stationary.request"),
  subscribeSnapshot: (handler: (snapshot: ControlSnapshot) => void) => {
    socket.on("control.snapshot", handler);
    return () => { socket.off("control.snapshot", handler); };
  },
  subscribeCommandEvents: (handler: (event: {event: string; error?: string}) => void) => {
    socket.on("command.event", handler);
    return () => { socket.off("command.event", handler); };
  },
  connect: (selectionId: string | null) => command("device.connect", {selection_id: selectionId}),
  disconnect: () => command("device.disconnect", {}),
  power: (on: boolean, generation: string) => command("main_power", {on, generation}),
  throttle: (assetId: string, speed: number, direction: string, generation: string) =>
    command("throttle", {asset_id: assetId, speed, direction, generation}),
  setFunction: (assetId: string, number: number, active: boolean, generation: string) =>
    command("function", {asset_id: assetId, number, active, generation}),
  stop: (assetId: string) => command("stop", {asset_id: assetId}),
  emergencyStop: () => command("emergency_stop", {}),
  resume: (generation: string) => command("resume", {generation}),
  turnout: (assetId: string, value: "straight" | "diverging") => command("turnout.set", {asset_id: assetId, value}),
  signal: (assetId: string, value: "stop" | "slow" | "go") => command("signal.set", {asset_id: assetId, value}),
  machine: (assetId: string, value: string) => command("machine.execute", {asset_id: assetId, value}),
};
