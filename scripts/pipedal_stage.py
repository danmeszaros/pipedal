#!/usr/bin/env python3
"""
pipedal_stage.py — stage display for PiPedal.

Connects to the PiPedal server websocket (the same one the web UI uses) and
shows, in large type, the current preset name, the active snapshot and the
on/off state of every effect in the chain. Updates live on preset/snapshot
changes, UI edits and MIDI-bound bypass switches.

Dependencies:   sudo apt install python3-websockets python3-tk
Usage:
    pipedal_stage.py                       # fullscreen Tk window, server on localhost:80
    pipedal_stage.py --host pi.local --port 8080
    pipedal_stage.py --windowed            # not fullscreen (for testing)
    pipedal_stage.py --console             # no GUI: print state on every change
    pipedal_stage.py --json                # no GUI: one JSON line per change (for piping)
    pipedal_stage.py --only "Overdrive,Delay"   # show only effects whose name contains one of these
Keys in the window: Esc / q = quit, f = toggle fullscreen.
"""

import argparse
import asyncio
import json
import queue
import sys
import threading
from dataclasses import dataclass, field, asdict

import websockets

SPLIT_URI = "uri://two-play/pipedal/pedalboard#Split"
SKIP_URIS = {
    "uri://two-play/pipedal/pedalboard#Empty",
    "uri://two-play/pipedal/pedalboard#Start",
    "uri://two-play/pipedal/pedalboard#End",
}

# Synthetic instance ids of the pedalboard's input / output volume stages.
# Subscribing to their VU gives the overall input and output levels.
VU_INPUT_ID = -2
VU_OUTPUT_ID = -3


# --------------------------------------------------------------------------
# State model
# --------------------------------------------------------------------------

@dataclass
class Effect:
    instance_id: int
    name: str
    enabled: bool


@dataclass
class StageState:
    connected: bool = False
    preset: str = ""
    preset_modified: bool = False
    snapshot: str = ""
    effects: list = field(default_factory=list)  # list[Effect]


class PiPedalState:
    """Holds raw server data and derives a StageState from it."""

    def __init__(self):
        self.presets = None      # {selectedInstanceId, presetChanged, presets:[{instanceId,name}]}
        self.pedalboard = None   # {name, items:[...], snapshots:[...], selectedSnapshot}
        self.connected = False

    # ---- updates from the server ----
    def set_item_enabled(self, instance_id, enabled):
        for item in self._iter_items(self.pedalboard.get("items", []) if self.pedalboard else []):
            if item.get("instanceId") == instance_id:
                item["isEnabled"] = enabled
                return True
        return False

    def set_selected_snapshot(self, index):
        if self.pedalboard is not None:
            self.pedalboard["selectedSnapshot"] = index

    # ---- derived view ----
    @staticmethod
    def _iter_items(items):
        for item in items or []:
            if item.get("uri") == SPLIT_URI:
                yield from PiPedalState._iter_items(item.get("topChain"))
                yield from PiPedalState._iter_items(item.get("bottomChain"))
            else:
                yield item

    def view(self) -> StageState:
        s = StageState(connected=self.connected)
        if self.presets:
            sel = self.presets.get("selectedInstanceId")
            for p in self.presets.get("presets", []):
                if p.get("instanceId") == sel:
                    s.preset = p.get("name", "")
            s.preset_modified = bool(self.presets.get("presetChanged"))
        if self.pedalboard:
            if not s.preset:
                s.preset = self.pedalboard.get("name", "")
            idx = self.pedalboard.get("selectedSnapshot", -1)
            snaps = self.pedalboard.get("snapshots") or []
            if idx is not None and 0 <= idx < len(snaps) and snaps[idx]:
                s.snapshot = snaps[idx].get("name") or f"Snapshot {idx + 1}"
            for item in self._iter_items(self.pedalboard.get("items")):
                if item.get("uri") in SKIP_URIS:
                    continue
                name = item.get("title") or item.get("pluginName") or "?"
                s.effects.append(Effect(item.get("instanceId", -1), name,
                                        bool(item.get("isEnabled"))))
        return s


# --------------------------------------------------------------------------
# Websocket client. Wire format: [ {message, replyTo|reply}, body? ]
# --------------------------------------------------------------------------

class PiPedalClient:
    def __init__(self, url, on_change, on_vu=None):
        self.url = url
        self.on_change = on_change   # called with StageState (from the client thread)
        self.on_vu = on_vu           # optional; called with each onVuUpdate body (client thread)
        self.state = PiPedalState()
        self._ws = None
        self._next_id = 1
        self._pending = {}

    async def _request(self, message, body=None, timeout=10):
        rid = self._next_id
        self._next_id += 1
        fut = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        hdr = {"message": message, "replyTo": rid}
        await self._ws.send(json.dumps([hdr] if body is None else [hdr, body]))
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(rid, None)

    def _emit(self):
        self.on_change(self.state.view())

    async def _refresh_presets(self):
        try:
            self.state.presets = await self._request("getPresets")
            self._emit()
        except Exception:
            pass

    async def _handle(self, raw):
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        if not isinstance(msg, list) or not msg:
            return
        hdr = msg[0]
        body = msg[1] if len(msg) > 1 else None

        if "reply" in hdr:
            fut = self._pending.get(hdr["reply"])
            if fut and not fut.done():
                fut.set_result(body)
            return

        m = hdr.get("message")
        changed = True
        if m == "onPresetsChanged":
            self.state.presets = body["presets"]
        elif m == "onPresetChanged":
            if self.state.presets is not None:
                self.state.presets["presetChanged"] = bool(body)
        elif m == "onPedalboardChanged":
            # Fired on preset load, snapshot load and structural edits.
            self.state.pedalboard = body["pedalboard"]
            asyncio.create_task(self._refresh_presets())
        elif m == "onItemEnabledChanged":
            # Fired for UI toggles and MIDI-bound bypass switches.
            changed = self.state.set_item_enabled(body["instanceId"], bool(body["enabled"]))
        elif m == "onSelectedSnapshotChanged":
            self.state.set_selected_snapshot(body)
        elif m == "onVuUpdate":
            # ~30/s per subscription. The ack below is required: the server
            # stops sending while an update is unacknowledged.
            if self.on_vu:
                self.on_vu(body)
            changed = False
        else:
            changed = False

        # Some notifications expect an acknowledgement.
        if "replyTo" in hdr:
            await self._ws.send(json.dumps([{"reply": hdr["replyTo"], "message": m}, True]))

        if changed:
            self._emit()

    async def _reader(self):
        async for raw in self._ws:
            await self._handle(raw)

    async def run_forever(self):
        delay = 1
        while True:
            try:
                # Pedalboard JSON can include plugin state blobs: no size limit.
                async with websockets.connect(self.url, max_size=None,
                                              ping_interval=20) as ws:
                    self._ws = ws
                    reader = asyncio.create_task(self._reader())
                    await self._request("hello")   # subscribes to notifications
                    if self.on_vu:
                        for iid in (VU_INPUT_ID, VU_OUTPUT_ID):
                            await self._request("addVuSubscription", iid)
                    self.state.pedalboard = await self._request("currentPedalboard")
                    self.state.presets = await self._request("getPresets")
                    self.state.connected = True
                    delay = 1
                    self._emit()
                    await reader
            except (OSError, asyncio.TimeoutError,
                    websockets.exceptions.WebSocketException) as e:
                print(f"pipedal: {e.__class__.__name__}: {e}", file=sys.stderr)
            finally:
                for fut in self._pending.values():
                    if not fut.done():
                        fut.cancel()
                self._pending.clear()
                if self.state.connected:
                    self.state.connected = False
                    self._emit()
            await asyncio.sleep(delay)
            delay = min(delay * 2, 10)


# --------------------------------------------------------------------------
# Outputs
# --------------------------------------------------------------------------

def filter_effects(state: StageState, only):
    if only:
        state.effects = [e for e in state.effects
                         if any(o.lower() in e.name.lower() for o in only)]
    return state


def run_console(client_factory, as_json, only):
    def on_change(s: StageState):
        s = filter_effects(s, only)
        if as_json:
            print(json.dumps(asdict(s), ensure_ascii=False), flush=True)
            return
        if not s.connected:
            print("-- disconnected --", flush=True)
            return
        mod = " *" if s.preset_modified else ""
        snap = f"  [{s.snapshot}]" if s.snapshot else ""
        fx = "  ".join(f"{e.name}:{'ON' if e.enabled else 'off'}" for e in s.effects)
        print(f"{s.preset}{mod}{snap}  |  {fx}", flush=True)

    try:
        asyncio.run(client_factory(on_change).run_forever())
    except KeyboardInterrupt:
        pass


def run_tk(client_factory, fullscreen, only):
    import tkinter as tk
    import tkinter.font as tkfont

    updates = queue.Queue()
    client = client_factory(lambda s: updates.put(s))
    threading.Thread(target=lambda: asyncio.run(client.run_forever()),
                     daemon=True).start()

    BG, FG, DIM = "#000000", "#ffffff", "#8a8a8a"
    ON_BG, ON_FG = "#1f9d3a", "#ffffff"
    OFF_BG, OFF_FG = "#262626", "#6a6a6a"
    WARN = "#ffb020"

    root = tk.Tk()
    root.title("PiPedal Stage")
    root.configure(bg=BG, cursor="none" if fullscreen else "")
    root.attributes("-fullscreen", fullscreen)
    root.bind("<Escape>", lambda e: root.destroy())
    root.bind("q", lambda e: root.destroy())
    root.bind("f", lambda e: root.attributes(
        "-fullscreen", not root.attributes("-fullscreen")))

    canvas = tk.Canvas(root, bg=BG, highlightthickness=0)
    canvas.pack(fill="both", expand=True)

    family = "DejaVu Sans"
    current = {"state": StageState()}

    def fit_font(text, max_w, max_h, weight="bold", lo=8, hi=600):
        """Largest single-line font size for text within max_w x max_h."""
        f = tkfont.Font(family=family, weight=weight)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            f.configure(size=-mid)       # negative = pixels
            if f.measure(text) <= max_w and f.metrics("linespace") <= max_h:
                lo = mid
            else:
                hi = mid - 1
        f.configure(size=-lo)
        return f

    fonts = []  # keep references alive

    def draw():
        s = current["state"]
        canvas.delete("all")
        fonts.clear()
        W, H = canvas.winfo_width(), canvas.winfo_height()
        if W < 10 or H < 10:
            return
        pad = int(min(W, H) * 0.03)

        if not s.connected:
            canvas.create_text(W - pad, pad, text="odpojeno", anchor="ne",
                               fill=WARN, font=(family, -max(14, H // 30)))

        # Layout: name ~55 %, snapshot ~12 %, effects ~33 % (if any)
        n_fx = len(s.effects)
        fx_h = int(H * 0.30) if n_fx else 0
        snap_h = int(H * 0.11) if s.snapshot else 0
        name_h = H - fx_h - snap_h - 2 * pad

        name = s.preset or "—"
        f = fit_font(name, W - 2 * pad, name_h * 0.9)
        fonts.append(f)
        canvas.create_text(W / 2, pad + name_h / 2, text=name, fill=FG, font=f)
        if s.preset_modified:
            canvas.create_text(pad, pad, text="●", anchor="nw", fill=WARN,
                               font=(family, -max(14, H // 25)))

        if s.snapshot:
            f2 = fit_font(s.snapshot, W - 2 * pad, snap_h * 0.85)
            fonts.append(f2)
            canvas.create_text(W / 2, pad + name_h + snap_h / 2,
                               text=s.snapshot, fill=DIM, font=f2)

        if n_fx:
            # Grid of tiles; choose column count that keeps tiles widest.
            top = H - pad - fx_h
            gap = max(4, pad // 2)
            best = None
            for cols in range(1, n_fx + 1):
                rows = -(-n_fx // cols)
                tw = (W - 2 * pad - (cols - 1) * gap) / cols
                th = (fx_h - (rows - 1) * gap) / rows
                score = min(tw / 4, th)  # prefer ~4:1 tiles
                if best is None or score > best[0]:
                    best = (score, cols, rows, tw, th)
            _, cols, rows, tw, th = best
            # One common font size so all labels match.
            longest = max((e.name for e in s.effects), key=len)
            ff = fit_font(longest, tw * 0.9, th * 0.7)
            fonts.append(ff)
            for i, e in enumerate(s.effects):
                r, c = divmod(i, cols)
                x0 = pad + c * (tw + gap)
                y0 = top + r * (th + gap)
                canvas.create_rectangle(x0, y0, x0 + tw, y0 + th, width=0,
                                        fill=ON_BG if e.enabled else OFF_BG)
                canvas.create_text(x0 + tw / 2, y0 + th / 2, text=e.name, font=ff,
                                   fill=ON_FG if e.enabled else OFF_FG)

    def poll():
        latest = None
        try:
            while True:
                latest = updates.get_nowait()
        except queue.Empty:
            pass
        if latest is not None:
            current["state"] = filter_effects(latest, only)
            draw()
        root.after(50, poll)

    canvas.bind("<Configure>", lambda e: draw())
    root.after(50, poll)
    root.mainloop()


def main():
    ap = argparse.ArgumentParser(description="Large-type stage display for PiPedal.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=80,
                    help="PiPedal web/websocket port (default 80)")
    ap.add_argument("--windowed", action="store_true", help="don't go fullscreen")
    ap.add_argument("--console", action="store_true", help="print to terminal, no GUI")
    ap.add_argument("--json", action="store_true", help="print JSON lines, no GUI")
    ap.add_argument("--only", default="",
                    help="comma-separated substrings; show only matching effects")
    args = ap.parse_args()

    url = f"ws://{args.host}:{args.port}/pipedal"
    only = [x.strip() for x in args.only.split(",") if x.strip()]
    factory = lambda cb: PiPedalClient(url, cb)

    if args.console or args.json:
        run_console(factory, args.json, only)
    else:
        run_tk(factory, not args.windowed, only)


if __name__ == "__main__":
    main()
