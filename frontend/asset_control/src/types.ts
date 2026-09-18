export type ConnectionState = "disconnected" | "connecting" | "ready" | "error";
export type PowerState = "unknown" | "off" | "on" | "fault";
export type Direction = "forward" | "reverse";

export type LocomotiveState = {
  address: number;
  speed: number;
  direction: Direction;
  functions: Record<string, boolean>;
  desired_functions: Record<string, boolean>;
};

export type DeviceState = {
  connection: ConnectionState;
  session_id: string | null;
  port: string | null;
  identity: string | null;
  firmware: string | null;
  last_seen: string | null;
  stale: boolean;
  main: {letter: string | null; mode: string | null; power: PowerState};
  error: string | null;
  locomotives: Record<string, LocomotiveState>;
};

export type ControlSnapshot = {
  generation: string;
  emergency_latched: boolean;
  device: DeviceState;
};

export type SessionSnapshot = ControlSnapshot & {csrf: string};

export type RosterLocomotive = {
  id: string;
  reporting_mark: string | null;
  road_number: string | null;
  prototype: string | null;
  address: number;
};

export type SerialDevice = {
  selection_id: string;
  port: string;
  description: string | null;
  manufacturer: string | null;
  vid: number | null;
  pid: number | null;
  serial_number: string | null;
};
