import { COORDINATE_SYSTEM, Deck, _GlobeController as GlobeController, _GlobeView as GlobeView } from "@deck.gl/core";
import { ArcLayer, GeoJsonLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { SimpleMeshLayer } from "@deck.gl/mesh-layers";
import { SphereGeometry } from "@luma.gl/engine";
import { SERVICE_ICONS } from "./service-icons.js";

const RATE_CAP = 20_000_000;
const MIN_ZOOM = -1;
const MAX_ZOOM = 12;
const EARTH_RADIUS_METERS = 6.3e6;
const LAND_URL = "https://d2ad6b4ur7yvpq.cloudfront.net/naturalearth-3.3.0/ne_50m_land.geojson";
const COUNTRY_URL = "https://d2ad6b4ur7yvpq.cloudfront.net/naturalearth-3.3.0/ne_110m_admin_0_countries.geojson";
const STATE_URL = "https://d2ad6b4ur7yvpq.cloudfront.net/naturalearth-3.3.0/ne_50m_admin_1_states_provinces.geojson";
const CITY_URL = "https://d2ad6b4ur7yvpq.cloudfront.net/naturalearth-3.3.0/ne_50m_populated_places_simple.geojson";
const ZOOM_STEP = 0.6;
const DESKTOP_ZOOM = 2.4;
const NO_TRANSITION = { transitionDuration: 0 };

function markerScale(zoom) {
  const ticks = (Number(zoom) - DESKTOP_ZOOM) / ZOOM_STEP;
  return Math.min(5, Math.max(0.75, 1.4 ** ticks));
}

function labelBand(zoom) {
  if (zoom < 3) return 0;
  if (zoom < 4.2) return 1;
  if (zoom < 5.6) return 2;
  if (zoom < 7) return 3;
  return 4;
}

function largestRing(geometry) {
  if (!geometry) return null;
  const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.type === "MultiPolygon" ? geometry.coordinates : [];
  let best = null;
  let bestArea = -1;
  for (const polygon of polygons) {
    const ring = polygon && polygon[0];
    if (!ring || ring.length < 4) continue;
    let area = 0;
    for (let index = 0; index < ring.length - 1; index += 1) {
      area += ring[index][0] * ring[index + 1][1] - ring[index + 1][0] * ring[index][1];
    }
    area = Math.abs(area);
    if (area > bestArea) {
      best = ring;
      bestArea = area;
    }
  }
  return best;
}

function featureCenter(geometry) {
  const ring = largestRing(geometry);
  if (!ring) return null;
  let longitude = 0;
  let latitude = 0;
  const count = ring.length - 1;
  for (let index = 0; index < count; index += 1) {
    longitude += ring[index][0];
    latitude += ring[index][1];
  }
  return [longitude / count, latitude / count];
}

function countryLabels(data) {
  return (data.features || []).flatMap((feature) => {
    const position = featureCenter(feature.geometry);
    const name = feature.properties && (feature.properties.name || feature.properties.admin);
    if (!position || !name) return [];
    return [{ position, name, rank: Number(feature.properties.labelrank) || 6 }];
  });
}

function stateLabels(data) {
  return (data.features || []).flatMap((feature) => {
    const position = featureCenter(feature.geometry);
    const name = feature.properties && feature.properties.name;
    if (!position || !name) return [];
    return [{ position, name, rank: Number(feature.properties.scalerank) || 8 }];
  });
}

function cityLabels(data) {
  return (data.features || []).flatMap((feature) => {
    const props = feature.properties || {};
    const longitude = Number(props.longitude);
    const latitude = Number(props.latitude);
    if (!Number.isFinite(longitude) || !Number.isFinite(latitude) || !props.name) return [];
    return [{
      position: [longitude, latitude],
      name: props.nameascii || props.name,
      rank: Number(props.scalerank) || 10,
      pop: Number(props.pop_max) || 0,
      world: Number(props.worldcity) || 0,
    }];
  });
}

function isTouchGesture(event) {
  return event.pointerType === "touch";
}

class MobileGlobeController extends GlobeController {
  setProps(props) {
    super.setProps(props);
    this.touchRotate = true;
    this.toggleEvents(
      ["multipanstart", "multipanmove", "multipanend"],
      Boolean(this.onViewStateChange)
    );
  }

  _onPanStart(event) {
    if (isTouchGesture(event)) return false;
    return super._onPanStart(event);
  }

  _onMultiPanStart(event) {
    const pos = this.getCenter(event);
    if (!this.isPointInBounds(pos, event)) return false;
    this.updateViewport(this.controllerState.panStart({ pos }), NO_TRANSITION, { isDragging: true });
    return true;
  }

  _onMultiPan(event) {
    if (!this.isDragging()) return false;
    const pos = this.getCenter(event);
    this.updateViewport(this.controllerState.pan({ pos }), NO_TRANSITION, {
      isDragging: true,
      isPanning: true,
    });
    return true;
  }

  _onMultiPanEnd(event) {
    if (!this.isDragging()) return false;
    this.updateViewport(this.controllerState.panEnd(), null, { isDragging: false, isPanning: false });
    return true;
  }
}

const CONTROLLER = {
  type: MobileGlobeController,
  scrollZoom: false,
  doubleClickZoom: true,
  touchZoom: true,
  dragRotate: true,
  dragPan: true,
};

function startingZoom() {
  return window.matchMedia("(max-width: 768px)").matches ? DESKTOP_ZOOM - ZOOM_STEP * 2 : DESKTOP_ZOOM;
}

function themeRgb(el, token, fallback) {
  const style = getComputedStyle(el);
  const raw = style.getPropertyValue(`--rgb-${token}-color`).trim();
  if (raw) {
    const parts = raw.split(",").map((part) => Number(part.trim()));
    if (parts.length >= 3 && parts.every((n) => Number.isFinite(n))) {
      return parts.slice(0, 3);
    }
  }
  const hex = style.getPropertyValue(`--${token}-color`).trim();
  const match = /^#?([0-9a-f]{6})$/i.exec(hex);
  if (match) {
    const value = match[1];
    return [
      parseInt(value.slice(0, 2), 16),
      parseInt(value.slice(2, 4), 16),
      parseInt(value.slice(4, 6), 16),
    ];
  }
  return fallback;
}

function darker(rgb) {
  return rgb.map((channel) => Math.round(channel * 0.65));
}

const POP_MS = 520;
const DRAW_MS = 860;
const FLOW_MS = 1400;

const flowModule = {
  name: "flow",
  vs: `
    in float instanceFlowModes;
    out float vPhase;
    out float vFlowMode;
  `,
  fs: `
    uniform flowUniforms {
      float time;
      float live;
    } flow;
    in float vPhase;
    in float vFlowMode;
    float flowHead(float wave) {
      float behind = fract(-wave);
      float comet = 1.0 - smoothstep(0.0, 0.2, behind);
      float second = 1.0 - smoothstep(0.0, 0.16, fract(-(wave + 0.5)));
      return max(comet, second * 0.55);
    }
  `,
  uniformTypes: { time: "f32", live: "f32" },
  defaultUniforms: { time: 0, live: 1 },
  inject: {
    "vs:#main-end": `
      vPhase = fract(sin(instanceSourcePositions.x * 12.9898 + instanceTargetPositions.y * 78.233) * 43758.5453);
      vFlowMode = instanceFlowModes;
    `,
    "fs:#main-end": `
      if (flow.live > 0.5) {
        float head = flowHead(fract(uv.x - flow.time + vPhase));
        head = max(head, flowHead(fract(1.0 - uv.x - flow.time + vPhase)) * step(0.5, vFlowMode));
        fragColor.rgb = mix(fragColor.rgb, min(fragColor.rgb * 2.4 + vec3(0.35), vec3(1.0)), head);
        fragColor.a = mix(fragColor.a, 1.0, head * 0.8);
      }
    `,
  },
};

class FlowArcLayer extends ArcLayer {
  initializeState() {
    super.initializeState();
    this.getAttributeManager().addInstanced({
      instanceFlowModes: {
        size: 1,
        accessor: "getFlowMode",
        defaultValue: 0,
      },
    });
  }

  getShaders() {
    const shaders = super.getShaders();
    return {
      ...shaders,
      modules: [...(shaders.modules || []), flowModule],
    };
  }

  draw(args) {
    const model = this.state.model;
    if (model) {
      model.shaderInputs.setProps({
        flow: {
          time: this.props.flowTime || 0,
          live: this.props.flowLive === false ? 0 : 1,
        },
      });
    }
    super.draw(args);
  }
}

FlowArcLayer.layerName = "FlowArcLayer";
FlowArcLayer.defaultProps = {
  flowTime: { type: "number", value: 0 },
  flowLive: { type: "boolean", value: true },
  getFlowMode: { type: "accessor", value: 0 },
};

function clamp01(value) {
  return Math.min(1, Math.max(0, value));
}

function easeInOutCubic(t) {
  const value = clamp01(t);
  return value < 0.5 ? 4 * value * value * value : 1 - ((-2 * value + 2) ** 3) / 2;
}

function easeOutBack(t) {
  const value = clamp01(t);
  const c1 = 1.70158;
  const c3 = c1 + 1;
  return 1 + c3 * (value - 1) ** 3 + c1 * (value - 1) ** 2;
}

function toVec(lon, lat) {
  const lambda = (lon * Math.PI) / 180;
  const phi = (lat * Math.PI) / 180;
  const cosPhi = Math.cos(phi);
  return [cosPhi * Math.cos(lambda), cosPhi * Math.sin(lambda), Math.sin(phi)];
}

function fromVec(vector) {
  return [
    (Math.atan2(vector[1], vector[0]) * 180) / Math.PI,
    (Math.asin(Math.min(1, Math.max(-1, vector[2]))) * 180) / Math.PI,
  ];
}

function alongArc(source, target, progress) {
  const amount = clamp01(progress);
  if (amount <= 0) return source;
  if (amount >= 1) return target;
  const from = toVec(source[0], source[1]);
  const to = toVec(target[0], target[1]);
  let dot = from[0] * to[0] + from[1] * to[1] + from[2] * to[2];
  dot = Math.min(1, Math.max(-1, dot));
  const omega = Math.acos(dot);
  if (omega < 1e-5) return source;
  const sinOmega = Math.sin(omega);
  const start = Math.sin((1 - amount) * omega) / sinOmega;
  const end = Math.sin(amount * omega) / sinOmega;
  return fromVec([
    from[0] * start + to[0] * end,
    from[1] * start + to[1] * end,
    from[2] * start + to[2] * end,
  ]);
}

function approach(value, goal, step) {
  if (value < goal) return Math.min(goal, value + step);
  if (value > goal) return Math.max(goal, value - step);
  return goal;
}

function radiusPx(rate) {
  return 4 + 24 * Math.min((Number(rate) || 0) / RATE_CAP, 1);
}

function clusterByOverlap(circles, project, unproject, facing, scale) {
  const placed = [];
  for (const circle of circles) {
    if (!facing(circle.lon, circle.lat)) continue;
    const pixel = project(circle.lon, circle.lat);
    if (!pixel || !Number.isFinite(pixel[0]) || !Number.isFinite(pixel[1])) continue;
    placed.push({
      circle,
      x: pixel[0],
      y: pixel[1],
      radius: radiusPx(circle.rate_bps) * (circle.pop || 1) * scale,
    });
  }
  const parent = placed.map((_, index) => index);
  const find = (index) => {
    let cursor = index;
    while (parent[cursor] !== cursor) {
      parent[cursor] = parent[parent[cursor]];
      cursor = parent[cursor];
    }
    return cursor;
  };
  for (let left = 0; left < placed.length; left += 1) {
    for (let right = left + 1; right < placed.length; right += 1) {
      const dx = placed[left].x - placed[right].x;
      const dy = placed[left].y - placed[right].y;
      const reach = placed[left].radius + placed[right].radius;
      if (dx * dx + dy * dy > reach * reach) continue;
      const leftRoot = find(left);
      const rightRoot = find(right);
      if (leftRoot !== rightRoot) parent[leftRoot] = rightRoot;
    }
  }
  const groups = new Map();
  for (let index = 0; index < placed.length; index += 1) {
    const root = find(index);
    if (!groups.has(root)) groups.set(root, []);
    groups.get(root).push(placed[index]);
  }
  const clusters = [];
  const at = new Map();
  for (const members of groups.values()) {
    let sx = 0;
    let sy = 0;
    let busiest = members[0];
    let rate = 0;
    let pixelRadius = 0;
    const kindRate = {};
    for (const member of members) {
      sx += member.x;
      sy += member.y;
      const memberRate = Number(member.circle.rate_bps) || 0;
      rate += memberRate;
      pixelRadius = Math.max(pixelRadius, member.radius);
      const kind = member.circle.kind || "out";
      kindRate[kind] = (kindRate[kind] || 0) + memberRate;
      if (memberRate > (Number(busiest.circle.rate_bps) || 0)) busiest = member;
    }
    let kind = busiest.circle.kind || "out";
    let bestKindRate = -1;
    for (const [name, value] of Object.entries(kindRate)) {
      if (value > bestKindRate) {
        bestKindRate = value;
        kind = name;
      }
    }
    const alone = members.length === 1;
    let lon = busiest.circle.lon;
    let lat = busiest.circle.lat;
    if (!alone) {
      const position = unproject([sx / members.length, sy / members.length]);
      if (position && Number.isFinite(position[0]) && Number.isFinite(position[1])) {
        lon = position[0];
        lat = position[1];
      }
    }
    const cluster = {
      ...busiest.circle,
      lon,
      lat,
      kind,
      rate_bps: alone ? busiest.circle.rate_bps : rate,
      pixelRadius,
      groupSize: members.length,
    };
    clusters.push(cluster);
    for (const member of members) at.set(member.circle.ip, [lon, lat]);
  }
  return { clusters, at };
}

function formatRate(bps) {
  const value = Number(bps) || 0;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)} Mbit/s`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(0)} kbit/s`;
  return `${value} bit/s`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

function formatBytes(bytes) {
  const value = Number(bytes) || 0;
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)} GB`;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)} MB`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(0)} KB`;
  if (value > 0) return `${value} B`;
  return "";
}

function resourceSection(peer) {
  if (peer.kind !== "in" || !Array.isArray(peer.resources)) return "";
  if (!peer.resources.length) {
    return `<div style="margin-top:12px;font-size:13px;opacity:.75;">No request in the access log yet.</div>`;
  }
  const rows = peer.resources
    .map((item) => {
      const size = item.open ? "in progress" : formatBytes(item.bytes);
      const target = `${item.host || ""}${item.path || ""}`;
      return `<tr><td style="padding:4px 8px 4px 0;white-space:nowrap;opacity:.8;">${escapeHtml(item.method || "GET")}</td><td style="padding:4px 8px 4px 0;word-break:break-all;">${escapeHtml(target)}</td><td style="padding:4px 0;text-align:right;white-space:nowrap;">${escapeHtml(size)}</td></tr>`;
    })
    .join("");
  return `<div style="margin-top:14px;font-size:11px;letter-spacing:.04em;opacity:.6;">RESOURCES</div><table style="width:100%;border-collapse:collapse;font-size:13px;">${rows}</table>`;
}

function placeParts(peer) {
  return [
    (peer.hostnames || []).filter(Boolean).join(", "),
    [peer.city || "", peer.country || ""].filter(Boolean).join(", "),
    peer.operator || "",
    peer.bot || "",
    kindLabel(peer.kind),
    formatRate(peer.rate_bps),
  ].filter(Boolean);
}

function serviceIcon(peer) {
  if (peer.kind !== "out") return "";
  const icon = SERVICE_ICONS[peer.operator];
  if (!icon) return "";
  return `<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" style="display:block;flex:none;fill:${icon.color}">${icon.body}</svg>`;
}

function arcLeg(point, mostar, home) {
  const remote = [point.lon, point.lat];
  const origin = point.kind === "torrent" && mostar ? mostar : home;
  if (point.kind === "torrent") {
    const seed = Number(point.seed_bps) > 0;
    const leech = Number(point.leech_bps) > 0;
    if (seed && !leech) return { source: origin, target: remote, flow: 0, inward: false };
    if (leech && !seed) return { source: remote, target: origin, flow: 0, inward: true };
    return { source: origin, target: remote, flow: 1, inward: false };
  }
  if (point.kind === "vpn") return { source: origin, target: remote, flow: 1, inward: false };
  if (point.kind === "in") return { source: remote, target: origin, flow: 0, inward: true };
  return { source: origin, target: remote, flow: 0, inward: false };
}

function torrentCaption(peer) {
  if (peer.kind !== "torrent") return "";
  const seed = Number(peer.seed_bps) > 0;
  const leech = Number(peer.leech_bps) > 0;
  const way = seed && leech ? "Seeding and leeching" : seed ? "Seeding" : leech ? "Leeching" : "";
  const names = (peer.torrents || []).filter(Boolean);
  return [names.join(" · "), way].filter(Boolean).join(" · ");
}

function flowKey(flow, peer) {
  const inbound = flow.inbound != null ? flow.inbound : peer.kind === "in";
  return [flow.protocol, flow.local_address, flow.local_port, inbound ? "in" : "out", flow.hostname || ""].join("|");
}

function flowCells(flow, peer) {
  const port = flow.local_port ? `:${flow.local_port}` : "";
  const who = flow.local_name ? `${flow.local_name} (${flow.local_address}${port})` : `${flow.local_address}${port}`;
  const inbound = flow.inbound != null ? flow.inbound : peer.kind === "in";
  const label = inbound ? "Destination" : "Source";
  const via = flow.hostname ? `${flow.hostname} · ` : "";
  return [String(flow.protocol || "").toUpperCase(), `${via}${label} ${who}`, formatRate(flow.rate_bps)];
}

function titleHtml(peer) {
  const vpn = peer.kind === "vpn" && peer.ppp_name ? ` · ${escapeHtml(peer.ppp_name)}` : "";
  return `${serviceIcon(peer)}<span>${escapeHtml(peer.ip)}${vpn}</span>`;
}

function kindLabel(kind) {
  if (kind === "in") return "Incoming";
  if (kind === "vpn") return "VPN";
  if (kind === "torrent") return "Torrent";
  return "Outgoing";
}

function uniqueSorted(values) {
  return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b));
}

function activeIncomingHosts(points) {
  const names = [];
  for (const point of points) {
    if (point.kind !== "in") continue;
    names.push(...(point.hostnames || []));
    for (const flow of point.flows || []) names.push(flow.hostname);
  }
  return uniqueSorted(names);
}

function activeLocalHosts(points) {
  const names = [];
  for (const point of points) {
    if (point.kind !== "out") continue;
    for (const flow of point.flows || []) names.push(flow.local_name);
  }
  return uniqueSorted(names);
}

function incomingHostMatches(point, host) {
  if ((point.hostnames || []).includes(host)) return true;
  return (point.flows || []).some((flow) => flow.hostname === host);
}

function localHostMatches(point, host) {
  return (point.flows || []).some((flow) => flow.local_name === host);
}

function activeVpnClients(points) {
  const names = [];
  for (const point of points) {
    if (point.kind === "vpn" && point.ppp_name) names.push(point.ppp_name);
  }
  return uniqueSorted(names);
}

function activeTorrentNames(points) {
  const names = [];
  for (const point of points) {
    if (point.kind !== "torrent") continue;
    names.push(...(point.torrents || []));
  }
  return uniqueSorted(names);
}

function nameFilter(point, hostIn, hostOut, vpnClient, torrentName) {
  if (point.kind === "in" && hostIn && !incomingHostMatches(point, hostIn)) return false;
  if (point.kind === "out" && hostOut && !localHostMatches(point, hostOut)) return false;
  if (point.kind === "vpn" && vpnClient && point.ppp_name !== vpnClient) return false;
  if (point.kind === "torrent" && torrentName && !(point.torrents || []).includes(torrentName)) return false;
  return true;
}

function flowRate(flows) {
  let total = 0;
  for (const flow of flows) total += Number(flow.rate_bps) || 0;
  return total;
}

function visibleBandwidth(point, hostIn, hostOut, vpnClient, torrentName) {
  if (!nameFilter(point, hostIn, hostOut, vpnClient, torrentName)) return 0;
  if (point.kind === "in" && hostIn) {
    return flowRate((point.flows || []).filter((flow) => flow.hostname === hostIn));
  }
  if (point.kind === "out" && hostOut) {
    return flowRate((point.flows || []).filter((flow) => flow.local_name === hostOut));
  }
  return Number(point.rate_bps) || 0;
}

function kindTotal(points, kind, hostIn, hostOut, vpnClient, torrentName) {
  let total = 0;
  for (const point of points) {
    if (point.kind !== kind) continue;
    total += visibleBandwidth(point, hostIn, hostOut, vpnClient, torrentName);
  }
  return total;
}

function itemRate(points, kind, name) {
  if (kind === "in") return kindTotal(points, "in", name, "", "", "");
  if (kind === "out") return kindTotal(points, "out", "", name, "", "");
  if (kind === "vpn") return kindTotal(points, "vpn", "", "", name, "");
  if (kind === "torrent") return kindTotal(points, "torrent", "", "", "", name);
  return 0;
}

function ratedLabel(name, rate) {
  return `${name} ${formatRate(rate)}`;
}

function matchingFlows(peer, hostIn, hostOut) {
  const flows = peer.flows || [];
  if (peer.kind === "in" && hostIn) return flows.filter((flow) => flow.hostname === hostIn);
  if (peer.kind === "out" && hostOut) return flows.filter((flow) => flow.local_name === hostOut);
  return flows;
}

class WanConnectionsMapCard extends HTMLElement {
  constructor() {
    super();
    this._config = {};
    this._built = false;
    this._modalPeer = null;
    this._centeredOnHome = false;
    this._viewState = {
      longitude: -40,
      latitude: 20,
      zoom: startingZoom(),
      minZoom: MIN_ZOOM,
      maxZoom: MAX_ZOOM,
      pitch: 0,
      bearing: 0,
    };
    this._shown = new Map();
    this._animFrame = 0;
    this._flowTime = 0;
    this._arcData = [];
    this._circleData = [];
    this._filters = { out: true, in: true, vpn: true, torrent: false };
    this._hostIn = "";
    this._hostOut = "";
    this._vpnClient = "";
    this._torrentName = "";
    this._hostFilterSig = "";
  }

  setConfig(config) {
    if (!config.entity) throw new Error("entity is required");
    this._config = config;
  }

  getGridOptions() {
    return { columns: "full" };
  }

  getCardSize() {
    return 9;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) {
      this._build();
      this._built = true;
    }
    this._render();
  }

  _build() {
    this.innerHTML = `
      <ha-card style="display:block;height:780px;width:100%;overflow:hidden;position:relative;background:#05070b;">
        <div class="map" style="position:absolute;inset:0;touch-action:pan-y;"></div>
        <div class="controls">
          <div class="zoom">
            <button type="button" class="zin" aria-label="Zoom in">+</button>
            <button type="button" class="zout" aria-label="Zoom out">−</button>
          </div>
          <div class="filters"></div>
        </div>
        <div class="stale" hidden>Snapshot stale</div>
        <div class="attr">IP Geolocation by DB-IP</div>
        <div class="modal" hidden></div>
        <style>
          @keyframes wan-flash { from { background-color: rgba(255,255,255,.22); } to { background-color: transparent; } }
          .flash { animation: wan-flash .7s ease; }
        </style>
      </ha-card>
    `;
    const card = this.querySelector("ha-card");
    card.querySelector(".controls").style.cssText =
      "position:absolute;right:12px;top:12px;z-index:4;display:flex;flex-direction:column;align-items:flex-end;gap:8px;";
    const filters = card.querySelector(".filters");
    filters.style.cssText = "display:flex;flex-direction:column;align-items:flex-end;gap:6px;";
    filters.addEventListener("pointerdown", (event) => event.stopPropagation());
    filters.addEventListener("click", (event) => event.stopPropagation());
    card.querySelector(".stale").style.cssText =
      "position:absolute;left:12px;top:12px;z-index:4;font-size:12px;padding:6px 10px;border-radius:8px;background:rgba(18,18,18,.85);color:#ffb74d;pointer-events:none;";
    card.querySelector(".attr").style.cssText =
      "position:absolute;right:8px;bottom:4px;z-index:4;font-size:10px;opacity:.7;color:var(--primary-text-color,#fff);pointer-events:none;";
    card.querySelector(".zoom").style.cssText = "display:flex;flex-direction:column;gap:6px;";
    for (const button of card.querySelectorAll(".zoom button")) {
      button.style.cssText =
        "width:32px;height:32px;border:0;border-radius:8px;background:rgba(18,18,18,.85);color:#fff;font-size:18px;cursor:pointer;";
    }
    const modal = card.querySelector(".modal");
    modal.style.cssText =
      "position:absolute;inset:0;z-index:30;background:rgba(0,0,0,.45);display:none;align-items:center;justify-content:center;";
    modal.addEventListener("click", (event) => {
      if (event.target === modal) this._closeModal();
    });
    card.querySelector(".zin").addEventListener("click", (event) => {
      event.stopPropagation();
      this._zoomBy(ZOOM_STEP);
    });
    card.querySelector(".zout").addEventListener("click", (event) => {
      event.stopPropagation();
      this._zoomBy(-ZOOM_STEP);
    });
    this._mountFilters(card.querySelector(".filters"));

    const mapDiv = card.querySelector(".map");
    this._deck = new Deck({
      parent: mapDiv,
      views: new GlobeView({ id: "globe" }),
      viewState: this._viewState,
      controller: CONTROLLER,
      touchAction: "pan-y",
      eventRecognizerOptions: {
        multipan: { direction: 15, pointers: 2, threshold: 10 },
      },
      pickingRadius: 10,
      getCursor: ({ isHovering }) => (isHovering ? "pointer" : "grab"),
      getTooltip: ({ object }) => {
        if (!object || !object.ip) return null;
        if (object.groupSize > 1) return `${object.groupSize} peers · ${formatRate(object.rate_bps)}`;
        return `${object.ip} · ${placeParts(object).join(" · ")} · ${object.count} connections`;
      },
      onViewStateChange: ({ viewState }) => {
        this._viewState = viewState;
        this._deck.setProps({ viewState });
        if (this._theme) this._pushLayers();
      },
      onClick: (info) => {
        if (info.object && info.object.ip) this._openModal(info.object);
      },
      layers: this._baseLayers(),
    });

    const fingers = new Set();
    const touchAction = (grabbed) => {
      const value = grabbed ? "none" : "pan-y";
      mapDiv.style.touchAction = value;
      const canvas = mapDiv.querySelector("canvas");
      if (canvas) canvas.style.touchAction = value;
    };
    touchAction(false);
    mapDiv.addEventListener("pointerdown", (event) => {
      if (event.pointerType !== "touch") return;
      fingers.add(event.pointerId);
      if (fingers.size >= 2) touchAction(true);
    });
    const releaseFinger = (event) => {
      fingers.delete(event.pointerId);
      if (fingers.size < 2) touchAction(false);
    };
    mapDiv.addEventListener("pointerup", releaseFinger);
    mapDiv.addEventListener("pointercancel", releaseFinger);

    const fit = () => {
      const width = mapDiv.clientWidth;
      const height = mapDiv.clientHeight;
      if (width && height) this._deck.setProps({ width, height });
    };
    requestAnimationFrame(fit);
    this._resize = new ResizeObserver(fit);
    this._resize.observe(mapDiv);
    this.style.display = "block";
    this.style.width = "100%";
  }

  _baseLayers() {
    if (this._earth) return this._earth;
    this._earth = [
      new SimpleMeshLayer({
        id: "earth-sphere",
        data: [0],
        mesh: new SphereGeometry({ radius: EARTH_RADIUS_METERS, nlat: 18, nlong: 36 }),
        coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
        getPosition: [0, 0, 0],
        getColor: [8, 12, 18],
        pickable: false,
      }),
      new GeoJsonLayer({
        id: "earth-land",
        data: LAND_URL,
        stroked: false,
        filled: true,
        getFillColor: [38, 44, 54],
        pickable: false,
      }),
    ];
    return this._earth;
  }

  _mountFilters(host) {
    host.replaceChildren();
    for (const kind of ["out", "in", "vpn", "torrent"]) {
      const group = document.createElement("div");
      group.dataset.kind = kind;
      group.style.cssText = "display:flex;flex-direction:column;align-items:flex-end;gap:6px;";
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.kind = kind;
      button.innerHTML = `<i></i><span></span>`;
      button.querySelector("span").textContent = kindLabel(kind);
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        this._filters[kind] = !this._filters[kind];
        this._afterFilterChange();
      });
      const slot = document.createElement("div");
      slot.className = "host-slot";
      slot.dataset.kind = kind;
      group.append(button, slot);
      host.appendChild(group);
    }
  }

  _paintFilters() {
    const colors = this._colors();
    const host = this.querySelector(".filters");
    if (!host) return;
    for (const button of host.querySelectorAll("button")) {
      const kind = button.dataset.kind;
      const live = (this._points || []).some((point) => point.kind === kind);
      const on = this._filters[kind] !== false;
      const [r, g, b] = colors[kind] || colors.out;
      const dot = button.querySelector("i");
      const total = kindTotal(this._points || [], kind, this._hostIn, this._hostOut, this._vpnClient, this._torrentName);
      const label = button.querySelector("span");
      if (label) label.textContent = total > 0 ? `${kindLabel(kind)} ${formatRate(total)}` : kindLabel(kind);
      button.setAttribute("aria-pressed", on ? "true" : "false");
      button.style.cssText =
        "align-items:center;gap:6px;border:0;border-radius:8px;padding:6px 10px;cursor:pointer;font-size:12px;color:#fff;background:rgba(18,18,18,.85);white-space:nowrap;opacity:" +
        (on ? "1" : "0.4") +
        ";display:" +
        (live ? "inline-flex" : "none") +
        ";";
      if (dot) dot.style.cssText = `display:inline-block;width:8px;height:8px;border-radius:50%;background:rgb(${r},${g},${b});`;
    }
    this._paintKindGroups();
  }

  _paintKindGroups() {
    const host = this.querySelector(".filters");
    if (!host) return;
    for (const group of host.querySelectorAll(":scope > div")) {
      const button = group.querySelector("button");
      const select = group.querySelector("select");
      const buttonShown = button && button.style.display !== "none";
      const selectShown = select && select.style.display !== "none";
      group.style.display = buttonShown || selectShown ? "flex" : "none";
    }
  }

  _pointVisible(point) {
    if (!point || this._filters[point.kind] === false) return false;
    return nameFilter(point, this._hostIn, this._hostOut, this._vpnClient, this._torrentName);
  }

  _afterFilterChange() {
    if (this._modalPeer && !this._pointVisible(this._modalPeer)) this._closeModal();
    else if (this._modalPeer) this._showModal(this._modalPeer);
    this._paintFilters();
    this._paintHostFilters();
    this._paintShown();
  }

  _syncHostFilters(points) {
    const lists = {
      in: activeIncomingHosts(points),
      out: activeLocalHosts(points),
      vpn: activeVpnClients(points),
      torrent: activeTorrentNames(points),
    };
    if (this._hostIn && !lists.in.includes(this._hostIn)) this._hostIn = "";
    if (this._hostOut && !lists.out.includes(this._hostOut)) this._hostOut = "";
    if (this._vpnClient && !lists.vpn.includes(this._vpnClient)) this._vpnClient = "";
    if (this._torrentName && !lists.torrent.includes(this._torrentName)) this._torrentName = "";
    const signature = ["in", "out", "vpn", "torrent"].map((kind) => lists[kind].join("\n")).join("\n--\n");
    if (signature !== this._hostFilterSig) {
      this._hostFilterSig = signature;
      this._mountHostFilters(lists);
      return;
    }
    this._paintHostFilters();
  }

  _mountHostFilters(lists) {
    const specs = [
      ["out", "All outgoing", "Outgoing local hostname", lists.out, this._hostOut],
      ["in", "All incoming", "Incoming hostname", lists.in, this._hostIn],
      ["vpn", "All VPN", "VPN client", lists.vpn, this._vpnClient],
      ["torrent", "All torrents", "Torrent", lists.torrent, this._torrentName],
    ];
    for (const [which, allLabel, aria, names, selected] of specs) {
      const slot = this.querySelector(`.host-slot[data-kind="${which}"]`);
      if (!slot) continue;
      slot.replaceChildren();
      if (!names.length) continue;
      slot.appendChild(this._hostSelect(which, allLabel, aria, names, selected));
    }
    this._paintHostFilters();
  }

  _hostSelect(which, allLabel, aria, names, selected) {
    const select = document.createElement("select");
    select.dataset.host = which;
    select.setAttribute("aria-label", aria);
    const all = document.createElement("option");
    all.value = "";
    all.dataset.base = allLabel;
    all.textContent = allLabel;
    select.appendChild(all);
    for (const name of names) {
      const option = document.createElement("option");
      option.value = name;
      option.dataset.base = name;
      option.textContent = name;
      select.appendChild(option);
    }
    select.value = names.includes(selected) ? selected : "";
    select.addEventListener("change", (event) => {
      event.stopPropagation();
      if (which === "in") this._hostIn = select.value;
      else if (which === "out") this._hostOut = select.value;
      else if (which === "vpn") this._vpnClient = select.value;
      else this._torrentName = select.value;
      this._afterFilterChange();
    });
    return select;
  }

  _paintHostFilters() {
    const host = this.querySelector(".filters");
    if (!host) return;
    const points = this._points || [];
    for (const select of host.querySelectorAll("select")) {
      const kind = select.dataset.host;
      const active = this._filters[kind] !== false;
      for (const option of select.querySelectorAll("option")) {
        const base = option.dataset.base || option.textContent;
        const rate = option.value ? itemRate(points, kind, option.value) : kindTotal(points, kind, "", "", "", "");
        option.textContent = ratedLabel(base, rate);
      }
      select.style.cssText =
        "max-width:min(320px,80vw);border:0;border-radius:8px;padding:6px 8px;font-size:12px;color:#fff;background:rgba(18,18,18,.85);display:" +
        (active ? "block" : "none") +
        ";";
    }
    this._paintKindGroups();
  }

  _zoomBy(delta) {
    const zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, (this._viewState.zoom || 0) + delta));
    this._viewState = { ...this._viewState, zoom };
    this._deck.setProps({ viewState: this._viewState });
    if (this._theme) this._pushLayers();
  }

  _colors() {
    const info = themeRgb(this, "info", [3, 155, 229]);
    const success = themeRgb(this, "success", [76, 175, 80]);
    const error = themeRgb(this, "error", [219, 68, 55]);
    const warning = themeRgb(this, "warning", [255, 152, 0]);
    return { out: info, in: success, vpn: error, torrent: warning };
  }

  _render() {
    if (!this._deck || !this._hass) return;
    const state = this._hass.states[this._config.entity];
    const points = state?.attributes?.points || [];
    this._points = points;
    const home = state?.attributes?.home || {};
    const colors = this._colors();
    this._syncHostFilters(points);
    this._paintFilters();
    const stale = this.querySelector(".stale");
    if (stale) stale.hidden = !state?.attributes?.stale;
    if (home.lat == null || home.lon == null) {
      this._deck.setProps({ layers: this._baseLayers() });
      return;
    }
    if (!this._centeredOnHome) {
      this._centeredOnHome = true;
      this._viewState = {
        ...this._viewState,
        longitude: home.lon,
        latitude: home.lat,
      };
      this._deck.setProps({ viewState: this._viewState });
    }
    this._origin = [home.lon, home.lat];
    const mostar = state?.attributes?.mostar || {};
    this._mostar =
      mostar.lat != null && mostar.lon != null ? [mostar.lon, mostar.lat] : null;
    this._theme = colors;
    this._syncShown(points);
    if (this._modalPeer) {
      const fresh = points.find((point) => point.ip === this._modalPeer.ip);
      if (fresh && this._pointVisible(fresh)) this._openModal(fresh);
      else this._closeModal();
    }
  }

  _syncShown(points) {
    const seen = new Set();
    for (const point of points) {
      if (!point.ip) continue;
      seen.add(point.ip);
      const leg = arcLeg(point, this._mostar, this._origin);
      const current = this._shown.get(point.ip);
      if (current) {
        const kindChanged = current.point.kind !== point.kind;
        current.point = point;
        current.source = leg.source;
        current.target = leg.target;
        current.flow = leg.flow;
        current.inward = leg.inward;
        current.leaving = false;
        if (kindChanged) {
          current.circle = 0;
          current.arc = 0;
        }
      } else {
        this._shown.set(point.ip, {
          point,
          source: leg.source,
          target: leg.target,
          flow: leg.flow,
          inward: leg.inward,
          circle: 0,
          arc: 0,
          leaving: false,
        });
      }
    }
    for (const [ip, item] of this._shown) {
      if (!seen.has(ip)) item.leaving = true;
    }
    this._paintShown();
    this._startAnim();
  }

  _shownMoving() {
    for (const item of this._shown.values()) {
      const goal = item.leaving ? 0 : 1;
      if (item.circle !== goal || item.arc !== goal) return true;
    }
    return false;
  }

  _flows() {
    return !this._config || this._config.flow !== false;
  }

  _startAnim() {
    if (!this._flows() && !this._shownMoving()) {
      this._paintShown();
      return;
    }
    if (this._animFrame) return;
    let last = performance.now();
    const step = (now) => {
      const dt = Math.min(48, now - last);
      last = now;
      const moving = this._shownMoving();
      for (const [ip, item] of this._shown) {
        const goal = item.leaving ? 0 : 1;
        item.circle = approach(item.circle, goal, dt / POP_MS);
        item.arc = approach(item.arc, goal, dt / DRAW_MS);
        if (item.leaving && item.circle === 0 && item.arc === 0) this._shown.delete(ip);
      }
      const flowing = this._flows();
      if (flowing) this._flowTime = (now % FLOW_MS) / FLOW_MS;
      if (moving || this._shownMoving()) this._paintShown();
      else if (flowing) this._pushLayers();
      if (this._shown.size && (flowing || this._shownMoving())) this._animFrame = requestAnimationFrame(step);
      else {
        this._paintShown();
        this._animFrame = 0;
      }
    };
    this._animFrame = requestAnimationFrame(step);
  }

  _paintShown() {
    if (!this._deck || !this._theme) return;
    const arcs = [];
    const circles = [];
    for (const item of this._shown.values()) {
      if (!this._pointVisible(item.point)) continue;
      const pop = Math.max(0, easeOutBack(item.circle));
      const draw = easeInOutCubic(item.arc);
      const rate = visibleBandwidth(item.point, this._hostIn, this._hostOut, this._vpnClient, this._torrentName);
      if (pop > 0.03) circles.push({ ...item.point, pop, rate_bps: rate });
      if (draw > 0.025) {
        const inward = Boolean(item.inward);
        arcs.push({
          ...item.point,
          rate_bps: rate,
          source: item.source,
          target: item.target,
          anchor: inward ? item.target : item.source,
          remote: inward ? item.source : item.target,
          draw,
          flow: item.flow || 0,
          inward,
        });
      }
    }
    this._arcData = arcs;
    this._circleData = circles;
    this._pushLayers();
  }

  _pushLayers() {
    if (!this._deck || !this._theme) return;
    const colors = this._theme;
    const colorOf = (point, end) => {
      const base = colors[point.kind] || colors.out;
      const rgb = end === "far" ? darker(base) : base;
      return [...rgb, Math.round(220 * (0.25 + 0.75 * (point.draw || 1)))];
    };
    const zoom = this._viewState.zoom || DESKTOP_ZOOM;
    const scale = markerScale(zoom);
    const band = labelBand(zoom);
    let viewport = null;
    if (this._deck.isInitialized) {
      try {
        viewport = this._deck.getViewports()[0] || null;
      } catch (_err) {
        viewport = null;
      }
    }
    const viewLon = this._viewState.longitude || 0;
    const viewLat = this._viewState.latitude || 0;
    const camera = toVec(viewLon, viewLat);
    const facing = (lon, lat) => {
      const place = toVec(lon, lat);
      return place[0] * camera[0] + place[1] * camera[1] + place[2] * camera[2] > 0.02;
    };
    let clusters = this._circleData;
    let clusterAt = new Map();
    if (viewport && this._circleData.length) {
      try {
        const grouped = clusterByOverlap(
          this._circleData,
          (lon, lat) => viewport.project([lon, lat]),
          (pixel) => viewport.unproject(pixel),
          facing,
          scale,
        );
        clusters = grouped.clusters;
        clusterAt = grouped.at;
      } catch (_err) {
        clusters = this._circleData;
        clusterAt = new Map();
      }
    }
    const border = [186, 194, 204, 170];
    const stateBorder = [160, 168, 178, 130];
    const label = [232, 236, 241, 230];
    const labelOutline = [5, 7, 11, 220];
    this._deck.setProps({
      layers: [
        ...this._baseLayers(),
        new GeoJsonLayer({
          id: "country-borders",
          data: COUNTRY_URL,
          stroked: true,
          filled: false,
          getLineColor: border,
          getLineWidth: 1,
          lineWidthUnits: "pixels",
          lineWidthMinPixels: 1,
          pickable: false,
        }),
        new GeoJsonLayer({
          id: "state-borders",
          data: STATE_URL,
          stroked: true,
          filled: false,
          visible: zoom >= 4.2,
          getLineColor: stateBorder,
          getLineWidth: 1,
          lineWidthUnits: "pixels",
          lineWidthMinPixels: 1,
          pickable: false,
        }),
        new TextLayer({
          id: "country-labels",
          data: COUNTRY_URL,
          dataTransform: countryLabels,
          getPosition: (d) => d.position,
          getText: (d) => (band === 0 ? d.rank <= 2 : band === 1 ? d.rank <= 4 : true) ? d.name : "",
          getSize: band >= 2 ? 15 : 12,
          getColor: label,
          outlineWidth: 3,
          outlineColor: labelOutline,
          fontSettings: { sdf: true },
          billboard: true,
          sizeUnits: "pixels",
          pickable: false,
          updateTriggers: { getText: band, getSize: band },
        }),
        new TextLayer({
          id: "state-labels",
          data: STATE_URL,
          dataTransform: stateLabels,
          visible: zoom >= 6,
          getPosition: (d) => d.position,
          getText: (d) => (d.rank <= (band >= 4 ? 5 : 2) ? d.name : ""),
          getSize: 12,
          getColor: label,
          outlineWidth: 3,
          outlineColor: labelOutline,
          fontSettings: { sdf: true },
          billboard: true,
          sizeUnits: "pixels",
          pickable: false,
          updateTriggers: { getText: band },
        }),
        new TextLayer({
          id: "city-labels",
          data: CITY_URL,
          dataTransform: cityLabels,
          visible: zoom >= 5.6,
          getPosition: (d) => d.position,
          getText: (d) => {
            if (band < 2) return "";
            if (band === 2) return d.world || d.pop >= 3_000_000 || d.rank <= 1 ? d.name : "";
            if (band === 3) return d.pop >= 800_000 || d.rank <= 3 ? d.name : "";
            return d.pop >= 200_000 || d.rank <= 6 ? d.name : "";
          },
          getSize: 12,
          getColor: label,
          outlineWidth: 3,
          outlineColor: labelOutline,
          fontSettings: { sdf: true },
          billboard: true,
          sizeUnits: "pixels",
          pickable: false,
          updateTriggers: { getText: band },
        }),
        new FlowArcLayer({
          id: "arcs",
          data: this._arcData,
          flowTime: this._flowTime,
          flowLive: this._flows(),
          getSourcePosition: (d) => {
            const remote = clusterAt.get(d.ip) || d.remote;
            return d.inward ? remote : d.anchor;
          },
          getTargetPosition: (d) => {
            const remote = clusterAt.get(d.ip) || d.remote;
            return alongArc(d.inward ? remote : d.anchor, d.inward ? d.anchor : remote, d.draw || 1);
          },
          getSourceColor: (d) => colorOf(d, d.inward ? "far" : "near"),
          getTargetColor: (d) => colorOf(d, d.inward ? "near" : "far"),
          getFlowMode: (d) => (d.flow ? 1 : 0),
          getWidth: (d) => Math.min(8, 1 + Math.log2(Math.max(1, d.count))),
          getHeight: 0.35,
          greatCircle: true,
          widthUnits: "pixels",
          pickable: false,
        }),
        new ScatterplotLayer({
          id: "peers",
          data: clusters,
          getPosition: (d) => [d.lon, d.lat],
          getRadius: (d) => d.pixelRadius || radiusPx(d.rate_bps) * d.pop * scale,
          radiusUnits: "pixels",
          billboard: true,
          stroked: true,
          filled: true,
          getFillColor: (d) => [...(colors[d.kind] || colors.out), Math.round(70 * Math.min(1, d.pop))],
          getLineColor: (d) => [...(colors[d.kind] || colors.out), Math.round(255 * Math.min(1, d.pop))],
          getLineWidth: 2,
          lineWidthUnits: "pixels",
          pickable: true,
          updateTriggers: { getRadius: zoom, getPosition: zoom },
        }),
        new TextLayer({
          id: "peer-groups",
          data: clusters.filter((circle) => circle.groupSize > 1),
          getPosition: (d) => [d.lon, d.lat],
          getText: (d) => String(d.groupSize),
          getSize: 12,
          getColor: [255, 255, 255, 235],
          outlineWidth: 3,
          outlineColor: labelOutline,
          fontSettings: { sdf: true },
          billboard: true,
          sizeUnits: "pixels",
          pickable: false,
          updateTriggers: { getText: zoom, getPosition: zoom },
        }),
        new ScatterplotLayer({
          id: "home",
          data: this._origin ? [this._origin] : [],
          getPosition: (d) => d,
          getRadius: 9 * scale,
          radiusUnits: "pixels",
          billboard: true,
          stroked: true,
          filled: true,
          getFillColor: [...colors.out, 90],
          getLineColor: [...colors.out, 255],
          getLineWidth: 2,
          lineWidthUnits: "pixels",
          pickable: false,
        }),
        new TextLayer({
          id: "home-label",
          data: this._origin ? [this._origin] : [],
          getPosition: (d) => d,
          getText: () => "Home",
          getSize: 14,
          getColor: [255, 255, 255, 240],
          outlineWidth: 3,
          outlineColor: labelOutline,
          fontSettings: { sdf: true },
          billboard: true,
          sizeUnits: "pixels",
          getTextAnchor: "start",
          getAlignmentBaseline: "center",
          getPixelOffset: [14, 0],
          pickable: false,
        }),
      ],
    });
  }

  _openModal(peer) {
    if (this._modalPeer) {
      this._showModal(peer);
      return;
    }
    requestAnimationFrame(() => this._showModal(peer));
  }

  _setFlash(node, text) {
    if (!node) return;
    const next = text || "";
    if (!next) {
      node.hidden = true;
      node.textContent = "";
      return;
    }
    node.hidden = false;
    if (node.textContent === next) return;
    node.textContent = next;
    node.classList.remove("flash");
    void node.offsetWidth;
    node.classList.add("flash");
  }

  _showModal(peer) {
    this._modalPeer = peer;
    const modal = this.querySelector(".modal");
    if (!modal) return;
    modal.hidden = false;
    modal.style.display = "flex";
    let sheet = modal.querySelector(".sheet");
    if (!sheet) {
      modal.innerHTML = `
        <div class="sheet" style="max-width:680px;width:92%;max-height:80%;overflow:auto;background:var(--ha-card-background,#1c1c1c);color:var(--primary-text-color,#fff);border-radius:14px;padding:16px;">
          <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;">
            <div style="min-width:0;">
              <div class="title" style="font-weight:700;display:flex;align-items:center;gap:8px;"></div>
              <div class="place" style="opacity:.75;font-size:13px;"></div>
              <div class="torrent" hidden style="margin-top:6px;font-size:13px;"></div>
            </div>
            <button type="button" class="close" style="background:transparent;color:inherit;border:0;font-size:18px;cursor:pointer;">×</button>
          </div>
          <table style="width:100%;margin-top:12px;border-collapse:collapse;font-size:13px;"><tbody class="flows"></tbody></table>
          <div class="resources"></div>
        </div>`;
      sheet = modal.querySelector(".sheet");
      modal.querySelector(".close").addEventListener("click", (event) => {
        event.stopPropagation();
        this._closeModal();
      });
      sheet.addEventListener("click", (event) => event.stopPropagation());
      if (this._deck) this._deck.setProps({ controller: false });
    }
    const title = sheet.querySelector(".title");
    const html = titleHtml(peer);
    if (title.dataset.html !== html) {
      title.dataset.html = html;
      title.innerHTML = html;
    }
    this._setFlash(sheet.querySelector(".place"), placeParts(peer).join(" · "));
    this._setFlash(sheet.querySelector(".torrent"), torrentCaption(peer));
    this._syncFlowRows(sheet.querySelector(".flows"), peer);
    this._syncResources(sheet.querySelector(".resources"), peer);
  }

  _syncFlowRows(tbody, peer) {
    const flows = matchingFlows(peer, this._hostIn, this._hostOut);
    const keys = flows.map((flow) => flowKey(flow, peer));
    const have = new Set(keys);
    for (const row of [...tbody.querySelectorAll("tr")]) {
      if (!have.has(row.dataset.key)) row.remove();
    }
    const existing = new Map([...tbody.querySelectorAll("tr")].map((row) => [row.dataset.key, row]));
    flows.forEach((flow, index) => {
      const key = keys[index];
      const cells = flowCells(flow, peer);
      let row = existing.get(key);
      if (!row) {
        row = document.createElement("tr");
        row.dataset.key = key;
        row.innerHTML = "<td></td><td></td><td style=\"text-align:right;white-space:nowrap;\"></td>";
        tbody.appendChild(row);
      }
      [...row.children].forEach((cell, cellIndex) => this._setFlash(cell, cells[cellIndex]));
    });
  }

  _syncResources(host, peer) {
    const resources =
      peer.kind === "in" && this._hostIn && Array.isArray(peer.resources)
        ? peer.resources.filter((item) => item.host === this._hostIn)
        : peer.resources;
    if (peer.kind !== "in" || !Array.isArray(resources)) {
      host.hidden = true;
      host.replaceChildren();
      return;
    }
    host.hidden = false;
    if (!resources.length) {
      const empty = this._hostIn ? "host" : "empty";
      const message = this._hostIn ? "No request for this hostname yet." : "No request in the access log yet.";
      if (host.dataset.mode !== empty) {
        host.dataset.mode = empty;
        host.innerHTML = `<div style="margin-top:12px;font-size:13px;opacity:.75;">${message}</div>`;
      }
      return;
    }
    if (host.dataset.mode !== "rows") {
      host.dataset.mode = "rows";
      host.innerHTML = `<div style="margin-top:14px;font-size:11px;letter-spacing:.04em;opacity:.6;">RESOURCES</div><table style="width:100%;border-collapse:collapse;font-size:13px;"><tbody></tbody></table>`;
    }
    const tbody = host.querySelector("tbody");
    const keys = resources.map((item) => `${item.method || "GET"}|${item.host || ""}|${item.path || ""}`);
    const have = new Set(keys);
    for (const row of [...tbody.querySelectorAll("tr")]) {
      if (!have.has(row.dataset.key)) row.remove();
    }
    const existing = new Map([...tbody.querySelectorAll("tr")].map((row) => [row.dataset.key, row]));
    resources.forEach((item, index) => {
      const key = keys[index];
      const size = item.open ? "in progress" : formatBytes(item.bytes);
      const target = `${item.host || ""}${item.path || ""}`;
      let row = existing.get(key);
      if (!row) {
        row = document.createElement("tr");
        row.dataset.key = key;
        row.innerHTML = `<td style="padding:4px 8px 4px 0;white-space:nowrap;opacity:.8;"></td><td style="padding:4px 8px 4px 0;word-break:break-all;"></td><td style="padding:4px 0;text-align:right;white-space:nowrap;"></td>`;
        tbody.appendChild(row);
      }
      const cells = [item.method || "GET", target, size];
      [...row.children].forEach((cell, cellIndex) => this._setFlash(cell, cells[cellIndex]));
    });
  }

  _closeModal() {
    this._modalPeer = null;
    const modal = this.querySelector(".modal");
    if (modal) {
      modal.hidden = true;
      modal.style.display = "none";
      modal.innerHTML = "";
    }
    if (this._deck) this._deck.setProps({ controller: CONTROLLER, viewState: this._viewState });
  }

  disconnectedCallback() {
    if (this._animFrame) cancelAnimationFrame(this._animFrame);
    this._animFrame = 0;
  }
}

customElements.define("wan-connections-map", WanConnectionsMapCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "wan-connections-map",
  name: "WAN Connections Map",
  description: "Globe of live WAN peers",
});
