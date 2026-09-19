import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type {
  ControlSnapshot,
  Direction,
  RosterLocomotive,
  SerialDevice,
  StationaryAsset,
} from "./types";

const initialSnapshot: ControlSnapshot = {
  generation: "",
  emergency_latched: false,
  device: {
    connection: "disconnected",
    session_id: null,
    port: null,
    identity: null,
    firmware: null,
    last_seen: null,
    stale: true,
    main: {letter: null, mode: null, power: "unknown"},
    error: null,
    locomotives: {},
  },
  mc: {broker: "offline", servo_gate: null, machine_gate: null, nodes: [], executions: []},
};

type PickerItem = {value: string; label: string};

function Picker({
  label,
  items,
  value,
  placeholder,
  disabled = false,
  onChange,
}: {
  label: string;
  items: PickerItem[];
  value: string;
  placeholder: string;
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const selected = items.find((item) => item.value === value);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function outside(event: PointerEvent) {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, []);

  return (
    <div className="picker-field" ref={root}>
      <span className="field-label">{label}</span>
      <button
        type="button"
        className="picker-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled || items.length === 0}
        onClick={() => setOpen((current) => !current)}
      >
        <span>{selected?.label ?? placeholder}</span><span aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="picker-options" role="listbox">
          {items.map((item) => (
            <button
              type="button"
              role="option"
              aria-selected={item.value === value}
              key={item.value}
              onClick={() => {
                onChange(item.value);
                setOpen(false);
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function App() {
  const [snapshot, setSnapshot] = useState(initialSnapshot);
  const [roster, setRoster] = useState<RosterLocomotive[]>([]);
  const [devices, setDevices] = useState<SerialDevice[]>([]);
  const [stationary, setStationary] = useState<StationaryAsset[]>([]);
  const [area, setArea] = useState<"operation" | "turnout" | "signal" | "machine">("operation");
  const [selectedStationary, setSelectedStationary] = useState("");
  const [selectedAsset, setSelectedAsset] = useState("");
  const [selectedDevice, setSelectedDevice] = useState("");
  const [direction, setDirection] = useState<Direction>("forward");
  const [speed, setSpeed] = useState(0);
  const [functionPage, setFunctionPage] = useState(0);
  const [functionStates, setFunctionStates] = useState<Record<string, Record<string, boolean>>>({});
  const [pendingFunctions, setPendingFunctions] = useState<Set<number>>(new Set());
  const [lifecycle, setLifecycle] = useState<"device" | "power" | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const throttleTimer = useRef<number | null>(null);
  const lifecycleRef = useRef(false);
  const pendingFunctionsRef = useRef<Set<number>>(new Set());

  const selectedLoco = roster.find((item) => item.id === selectedAsset);
  const ready = snapshot.device.connection === "ready";
  const canOperate = ready && snapshot.device.main.power === "on" &&
    !snapshot.emergency_latched && Boolean(selectedLoco) && lifecycle === null;

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const session = await api.session();
        const [locomotives, serialDevices, stationaryAssets] = await Promise.allSettled([
          api.locomotives(), api.devices(), api.stationary(),
        ]);
        if (!active) return;
        setSnapshot(session);
        if (locomotives.status === "fulfilled") {
          setRoster(locomotives.value.items);
          if (locomotives.value.items.length === 1) setSelectedAsset(locomotives.value.items[0].id);
        }
        if (serialDevices.status === "fulfilled") {
          setDevices(serialDevices.value.items);
          if (serialDevices.value.items.length === 1) setSelectedDevice(serialDevices.value.items[0].selection_id);
        }
        if (stationaryAssets.status === "fulfilled") setStationary(stationaryAssets.value.items);
        const failed = [locomotives, serialDevices, stationaryAssets].find(
          (result): result is PromiseRejectedResult => result.status === "rejected",
        );
        setMessage(failed ? (failed.reason instanceof Error ? failed.reason.message : "Unable to load controls") : null);
      } catch (error) {
        if (active) setMessage(error instanceof Error ? error.message : "Unable to load controls");
      } finally {
        if (active) setLoaded(true);
      }
    }
    load();
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const removeSnapshot = api.subscribeSnapshot((value) => {
      if (!lifecycleRef.current && pendingFunctionsRef.current.size === 0) setSnapshot(value);
    });
    const removeEvents = api.subscribeCommandEvents((event) => {
      if (event.event === "command.failed") setMessage(event.error ?? "Command failed");
    });
    return () => { removeSnapshot(); removeEvents(); };
  }, []);

  useEffect(() => {
    if (!selectedLoco) return;
    const reported = snapshot.device.locomotives[String(selectedLoco.address)]?.desired_functions;
    if (!reported) return;
    setFunctionStates((current) => {
      const merged = {...current[selectedAsset]};
      for (const [number, active] of Object.entries(reported)) {
        if (!pendingFunctionsRef.current.has(Number(number))) merged[number] = active;
      }
      return {...current, [selectedAsset]: merged};
    });
  }, [snapshot.device.locomotives, selectedAsset, selectedLoco]);

  async function runLifecycle(kind: "device" | "power", action: () => Promise<unknown>) {
    if (lifecycleRef.current) return;
    lifecycleRef.current = true;
    setLifecycle(kind);
    setMessage(null);
    try {
      await action();
      setSnapshot(await api.snapshot());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Operation failed");
    } finally {
      lifecycleRef.current = false;
      setLifecycle(null);
    }
  }

  async function run(action: () => Promise<unknown>) {
    setMessage(null);
    try {
      await action();
      setSnapshot(await api.snapshot());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Operation failed");
    }
  }

  function scheduleThrottle(nextSpeed: number, nextDirection = direction) {
    setSpeed(nextSpeed);
    if (!canOperate || !selectedAsset) return;
    if (throttleTimer.current !== null) window.clearTimeout(throttleTimer.current);
    const generation = snapshot.generation;
    throttleTimer.current = window.setTimeout(() => {
      run(() => api.throttle(selectedAsset, nextSpeed, nextDirection, generation));
    }, 100);
  }

  function changeDirection(next: Direction) {
    if (next === direction) return;
    setDirection(next);
    scheduleThrottle(0, next);
  }

  async function toggleFunction(number: number) {
    if (!canOperate || !selectedAsset || pendingFunctions.has(number)) return;
    const previous = functionStates[selectedAsset]?.[String(number)] === true;
    const next = !previous;
    setMessage(null);
    setFunctionStates((current) => ({
      ...current,
      [selectedAsset]: {...current[selectedAsset], [String(number)]: next},
    }));
    pendingFunctionsRef.current.add(number);
    setPendingFunctions((current) => new Set(current).add(number));
    try {
      await api.setFunction(selectedAsset, number, next, snapshot.generation);
      setSnapshot(await api.snapshot());
    } catch (error) {
      setFunctionStates((current) => ({
        ...current,
        [selectedAsset]: {...current[selectedAsset], [String(number)]: previous},
      }));
      setMessage(error instanceof Error ? error.message : "Function command failed");
    } finally {
      pendingFunctionsRef.current.delete(number);
      setPendingFunctions((current) => {
        const updated = new Set(current);
        updated.delete(number);
        return updated;
      });
    }
  }

  const rosterItems = useMemo(() => roster.map((item) => ({
    value: item.id,
    label: `${[item.reporting_mark, item.road_number].filter(Boolean).join(" ") || item.id}${item.prototype ? ` · ${item.prototype}` : ""}`,
  })), [roster]);
  const deviceItems = useMemo(() => devices.map((item) => ({
    value: item.selection_id,
    label: `${item.port} · ${item.description || "serial device"}`,
  })), [devices]);
  const firstFunction = functionPage * 16;
  const lastFunction = Math.min(firstFunction + 15, 68);
  const familyAssets = stationary.filter((item) => item.family === area);
  const selectedAccessory = familyAssets.find((item) => item.id === selectedStationary);
  const selectedNode = snapshot.mc.nodes.find((node) => node.node_id === selectedAccessory?.node_id);
  const accessoryReady = snapshot.mc.broker === "connected" && selectedNode?.ready === true;
  const latestAccessoryExecution = snapshot.mc.executions.find((item) => item.asset_id === selectedStationary);

  useEffect(() => {
    if (area === "operation") return;
    const items = stationary.filter((item) => item.family === area);
    setSelectedStationary(items.length === 1 ? items[0].id : "");
  }, [area, stationary]);

  return (
    <main className="shell">
      <header className="topbar">
        <img className="brand-logo" src="/static/mtos-logo-wireframe.png" alt="" />
        <div>
          <p className="eyebrow">MTOS · HMI</p>
          <h1>Locomotive control</h1>
        </div>
        <button
          className="emergency"
          aria-label="Emergency stop all locomotives"
          disabled={!ready}
          onClick={() => {
            if (throttleTimer.current !== null) window.clearTimeout(throttleTimer.current);
            setSpeed(0);
            run(api.emergencyStop);
          }}
        >
          <svg viewBox="0 0 48 48" aria-hidden="true">
            <path d="M24 1.5Q27.2 1.5 29.2 5L47 36.2Q51.5 44 42.5 46.5H5.5Q-3.5 44 1 36.2L18.8 5Q20.8 1.5 24 1.5Z" fill="#f32636"/>
            <path d="M24 5.2Q26.5 5.2 28 8L43.9 35.9Q47.3 41.7 40.5 43.4H7.5Q.7 41.7 4.1 35.9L20 8Q21.5 5.2 24 5.2Z" fill="#fff"/>
            <path d="M24 8.4Q25.8 8.4 27 10.6L41.2 35.7Q43.5 39.7 38.8 40.5H9.2Q4.5 39.7 6.8 35.7L21 10.6Q22.2 8.4 24 8.4Z" fill="#f32636"/>
            <rect x="22" y="18" width="4" height="13" rx="2" fill="#fff"/><circle cx="24" cy="35.8" r="2.3" fill="#fff"/>
          </svg>
        </button>
      </header>

      {message && <p className="message" role="alert">{message}</p>}

      {area === "operation" && <section className="panel device-panel" aria-label="EX-CSB1 command station">
        <div className="row">
          <div><h2>EX-CSB1</h2><span className="device-kind">USB · serial command station</span></div>
          <span className={`pill ${snapshot.device.connection === "error" ? "error" : ""}`}>
            {lifecycle === "device" ? (ready ? "disconnecting" : "connecting") : snapshot.device.connection}
          </span>
        </div>
        <div className="row power">
          <span>MAIN track power</span>
          <strong>{lifecycle === "power" ? (snapshot.device.main.power === "on" ? "TURNING OFF" : "TURNING ON") : snapshot.device.main.power.toUpperCase()}</strong>
        </div>
        <div className="actions">
          <button
            className={lifecycle === "device" ? "pending" : ""}
            disabled={lifecycle !== null}
            onClick={() => runLifecycle("device", ready ? api.disconnect : () => api.connect(selectedDevice || null))}
          >
            {lifecycle === "device" ? (ready ? "Disconnecting…" : "Connecting…") : (ready ? "Disconnect" : "Connect")}
          </button>
          <button
            className={lifecycle === "power" ? "pending" : ""}
            disabled={!ready || lifecycle !== null}
            onClick={() => runLifecycle("power", () => api.power(snapshot.device.main.power !== "on", snapshot.generation))}
          >
            {lifecycle === "power" ? (snapshot.device.main.power === "on" ? "Powering OFF…" : "Powering ON…") : (snapshot.device.main.power === "on" ? "Power OFF" : "Power ON")}
          </button>
        </div>
        <details>
          <summary>Connection details</summary>
          <Picker label="Serial device" items={deviceItems} value={selectedDevice}
            placeholder={devices.length ? "Select serial device" : "No serial devices found"}
            disabled={ready || lifecycle !== null} onChange={setSelectedDevice} />
          <p>{snapshot.device.identity || snapshot.device.error || "No verified identity"}</p>
        </details>
      </section>}

      <nav className="tabs" aria-label="Control area">
        <button className={area === "operation" ? "current" : ""} aria-current={area === "operation" ? "page" : undefined} onClick={() => setArea("operation")}>Operation</button>
        <button disabled>Programming</button>
        <button className={area === "turnout" ? "current" : ""} onClick={() => setArea("turnout")}>Turnout</button>
        <button className={area === "signal" ? "current" : ""} onClick={() => setArea("signal")}>Signal</button>
        <button className={area === "machine" ? "current" : ""} onClick={() => setArea("machine")}>Machine</button>
      </nav>

      {area !== "operation" && (
        <section className="panel accessory-panel">
          <div className="row">
            <h2>{area[0].toUpperCase() + area.slice(1)}</h2>
            <span className={`pill ${accessoryReady ? "" : "error"}`}>{accessoryReady ? "ready" : snapshot.mc.broker}</span>
          </div>
          <Picker label={`Active ${area}`} items={familyAssets.map((item) => ({value: item.id, label: item.label || `${item.id} · ${item.type}`}))}
            value={selectedStationary} placeholder={familyAssets.length ? `Select ${area}` : `No active ${area}s`}
            onChange={setSelectedStationary} />
          {selectedAccessory && <small>{selectedAccessory.id} · {selectedAccessory.node_id} · {selectedAccessory.type}</small>}
          {latestAccessoryExecution && <p className="notice">{latestAccessoryExecution.operation}: {latestAccessoryExecution.state}</p>}
          <div className="state-actions">
            {area === "turnout" && <><button disabled={!accessoryReady} onClick={() => run(() => api.turnout(selectedStationary, "straight"))}>Straight</button><button disabled={!accessoryReady} onClick={() => run(() => api.turnout(selectedStationary, "diverging"))}>Diverging</button></>}
            {area === "signal" && <><button disabled={!accessoryReady} onClick={() => run(() => api.signal(selectedStationary, "stop"))}>Stop</button>{selectedAccessory?.type.endsWith("3a") && <button disabled={!accessoryReady} onClick={() => run(() => api.signal(selectedStationary, "slow"))}>Slow</button>}<button disabled={!accessoryReady} onClick={() => run(() => api.signal(selectedStationary, "go"))}>Go</button></>}
            {area === "machine" && (selectedAccessory?.actions || []).map((action) => <button key={action} disabled={!accessoryReady} onClick={() => run(() => api.machine(selectedStationary, action))}>{action.replaceAll("_", " ")}</button>)}
          </div>
          {!accessoryReady && <p className="notice">MC broker or node is not ready. No command will be sent.</p>}
        </section>
      )}

      {area === "operation" && <><section className="panel roster-panel">
        <Picker label="Active locomotive" items={rosterItems} value={selectedAsset}
          placeholder={roster.length ? "Select locomotive" : "No active locomotives"}
          disabled={pendingFunctions.size > 0}
          onChange={(value) => {setSelectedAsset(value); setSpeed(0);}} />
        <small>{selectedLoco ? `${selectedLoco.id} · DCC ${selectedLoco.address}` : ""}</small>
      </section>

      <section className="panel throttle-panel">
        <h2>Throttle</h2>
        {snapshot.emergency_latched && <p className="notice">Emergency stop active. Resume explicitly.</p>}
        <div className="directions">
          <button className={direction === "reverse" ? "selected" : ""} disabled={!canOperate} onClick={() => changeDirection("reverse")}>← Reverse</button>
          <button className={direction === "forward" ? "selected" : ""} disabled={!canOperate} onClick={() => changeDirection("forward")}>Forward →</button>
        </div>
        <div className="row speed-row"><label htmlFor="speed">Speed</label><strong>{speed}<small> / 126</small></strong></div>
        <input id="speed" className="range" type="range" min="0" max="126" value={speed} disabled={!canOperate} onChange={(event) => scheduleThrottle(Number(event.target.value))} />
        <div className="speed-actions">
          <button aria-label="Decrease speed" disabled={!canOperate} onClick={() => scheduleThrottle(Math.max(0, speed - 1))}>−</button>
          <button className="loco-stop" disabled={!ready || !selectedAsset} onClick={() => {
            if (throttleTimer.current !== null) window.clearTimeout(throttleTimer.current);
            setSpeed(0); run(() => api.stop(selectedAsset));
          }}>Stop locomotive</button>
          <button aria-label="Increase speed" disabled={!canOperate} onClick={() => scheduleThrottle(Math.min(126, speed + 1))}>+</button>
        </div>
        {snapshot.emergency_latched && <button onClick={() => run(() => api.resume(snapshot.generation))}>Resume controls</button>}
      </section>

      <section className="panel function-panel">
        <div className="row">
          <h2>Functions</h2>
          <div className="bank-nav">
            <button aria-label="Previous function page" disabled={functionPage === 0} onClick={() => setFunctionPage((value) => Math.max(0, value - 1))}>◀</button>
            <span>F{firstFunction}–F{lastFunction}</span>
            <button aria-label="Next function page" disabled={functionPage === 4} onClick={() => setFunctionPage((value) => Math.min(4, value + 1))}>▶</button>
          </div>
        </div>
        <div className="function-grid" aria-label={`Locomotive functions F${firstFunction} through F${lastFunction}`}>
          {Array.from({length: lastFunction - firstFunction + 1}, (_, offset) => {
            const number = firstFunction + offset;
            const active = functionStates[selectedAsset]?.[String(number)] === true;
            const pending = pendingFunctions.has(number);
            return (
              <button
                type="button"
                key={number}
                className={`${active ? "active" : ""} ${pending ? "pending" : ""}`}
                aria-pressed={active}
                aria-busy={pending}
                disabled={!canOperate}
                onClick={() => toggleFunction(number)}
              >
                <span>F{number}</span>
                <small>{number === 0 ? "Headlight" : number === 1 ? "Bell" : number === 2 ? "Horn" : "Sound"}</small>
              </button>
            );
          })}
        </div>
      </section></>}
    </main>
  );
}
