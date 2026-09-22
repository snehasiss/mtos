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
  prog: {letter: string | null; mode: string | null; power: PowerState};
  error: string | null;
  locomotives: Record<string, LocomotiveState>;
};

export type ControlSnapshot = {
  generation: string;
  emergency_latched: boolean;
  device: DeviceState;
  mc: {
    broker: "connected" | "offline";
    servo_gate: string | null;
    machine_gate: string | null;
    nodes: Array<{node_id: string; availability: string; ready: boolean; configuration_revision: number | null}>;
    executions: Array<{execution_id: string; asset_id: string; state: string; operation: string; result: Record<string, unknown> | null}>;
  };
};

export type SessionSnapshot = ControlSnapshot & {csrf: string};

export type RosterLocomotive = {
  id: string;
  reporting_mark: string | null;
  road_number: string | null;
  prototype: string | null;
  address: number;
};

export type ProgrammingAsset = RosterLocomotive & {
  revision: number;
  status: "maintenance";
  location: "test_prog_1";
};

export type CommandEvent = {
  event: string;
  command_id?: string;
  error?: string;
  result?: Record<string, any>;
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

export type StationaryAsset = {
  id: string;
  family: "turnout" | "signal" | "machine";
  type: string;
  label: string | null;
  node_id: string;
  revision: number;
  configuration_revision: number;
  actions: string[];
};
