import type { Scenario, Station } from "./types";

export interface LayoutPoint {
  x: number;
  y: number;
  labelDx?: number;
  labelDy?: number;
}

export interface SegmentStyleHint {
  curve?: number;
  controlDx?: number;
  controlDy?: number;
  labelDx?: number;
  labelDy?: number;
}

export interface ScenarioLayout {
  viewBox: string;
  nodes: Record<string, LayoutPoint>;
  segments: Record<string, SegmentStyleHint>;
}

export const threeStationLayout: ScenarioLayout = {
  viewBox: "0 0 1000 560",
  nodes: {
    L_exit_lr: { x: 118, y: 225, labelDx: -34, labelDy: -18 },
    L_platform_exit: { x: 76, y: 252, labelDx: -70, labelDy: -10 },
    L_platform_entry: { x: 76, y: 328, labelDx: -72, labelDy: 18 },
    L_entry_rl: { x: 118, y: 355, labelDx: -34, labelDy: 38 },
    R_entry_lr: { x: 882, y: 225, labelDx: 10, labelDy: -18 },
    R_platform_entry: { x: 924, y: 252, labelDx: 12, labelDy: -10 },
    R_platform_exit: { x: 924, y: 328, labelDx: 12, labelDy: 18 },
    R_exit_rl: { x: 882, y: 355, labelDx: 10, labelDy: 38 },
    M_entry_lr: { x: 350, y: 205, labelDx: -42, labelDy: -26 },
    M_service_approach_lr: { x: 410, y: 150 },
    M_platform_entry_lr: { x: 470, y: 130, labelDx: -30, labelDy: -26 },
    M_platform_exit_lr: { x: 540, y: 130, labelDx: 0, labelDy: -26 },
    M_service_accelerate_lr: { x: 600, y: 150 },
    M_exit_lr: { x: 660, y: 205, labelDx: 8, labelDy: -26 },
    M_entry_rl: { x: 660, y: 355, labelDx: 8, labelDy: 36 },
    M_service_approach_rl: { x: 600, y: 410 },
    M_platform_entry_rl: { x: 540, y: 430, labelDx: 0, labelDy: 42 },
    M_platform_exit_rl: { x: 470, y: 430, labelDx: -34, labelDy: 42 },
    M_service_accelerate_rl: { x: 410, y: 410 },
    M_exit_rl: { x: 350, y: 355, labelDx: -44, labelDy: 36 },
  },
  segments: {
    L_exit_lr_to_M_entry_lr: { curve: -10, labelDx: -72, labelDy: -18 },
    M_exit_lr_to_R_entry_lr: { curve: -10, labelDx: 56, labelDy: -18 },
    R_exit_rl_to_M_entry_rl: { curve: -10, labelDx: 64, labelDy: 30 },
    M_exit_rl_to_L_entry_rl: { curve: -10, labelDx: -86, labelDy: 30 },
    L_turnaround_decelerate: { labelDx: -36, labelDy: 20 },
    L_turnaround_platform: { labelDx: -50, labelDy: 0 },
    L_turnaround_accelerate: { labelDx: -36, labelDy: -18 },
    R_turnaround_decelerate: { labelDx: 36, labelDy: -18 },
    R_turnaround_platform: { labelDx: 50, labelDy: 0 },
    R_turnaround_accelerate: { labelDx: 36, labelDy: 20 },
    M_lr_skip_bypass: { curve: -60, labelDx: 4, labelDy: -52 },
    M_rl_skip_bypass: { curve: -60, labelDx: 2, labelDy: 64 },
  },
};

export function layoutForScenario(scenario: Scenario): ScenarioLayout {
  if (scenario.scenario_id === "three_station_v0" || scenario.scenario_id.startsWith("three_station_")) {
    return threeStationLayout;
  }
  if (isCircularScenario(scenario)) {
    return circularSkipStopLayout(scenario);
  }
  return linearSkipStopLayout(scenario);
}

export function isCircularScenario(scenario: Scenario): boolean {
  return scenario.scenario_id.startsWith("five_station_circle_cw")
    || scenario.scenario_id.startsWith("thesis_t5r_")
    || scenario.scenario_id.startsWith("thesis_t6r_");
}

function linearSkipStopLayout(scenario: Scenario): ScenarioLayout {
  const passengerStations = scenario.stations.filter((station) => station.kind === "terminal" || station.kind === "service");
  if (passengerStations.length < 3) return threeStationLayout;

  const width = Math.max(1000, 240 * (passengerStations.length - 1) + 220);
  const leftPad = 90;
  const rightPad = 90;
  const topY = 178;
  const bottomY = 422;
  const terminalPlatformTopY = 242;
  const terminalPlatformBottomY = 338;
  const middleTopPlatformY = 118;
  const middleBottomPlatformY = 482;
  const usableWidth = width - leftPad - rightPad;
  const step = usableWidth / (passengerStations.length - 1);

  const nodes: Record<string, LayoutPoint> = {};
  const segments: Record<string, SegmentStyleHint> = {};

  passengerStations.forEach((station, index) => {
    const x = leftPad + step * index;
    if (index === 0) {
      addLeftTerminal(nodes, station, x, topY, bottomY, terminalPlatformTopY, terminalPlatformBottomY);
      addTerminalSegmentHints(segments, station.id, "left");
      return;
    }
    if (index === passengerStations.length - 1) {
      addRightTerminal(nodes, station, x, topY, bottomY, terminalPlatformTopY, terminalPlatformBottomY);
      addTerminalSegmentHints(segments, station.id, "right");
      return;
    }
    addMiddleStation(nodes, station, x, topY, bottomY, middleTopPlatformY, middleBottomPlatformY);
    segments[`${station.id}_lr_skip_bypass`] = { curve: -48, labelDx: 0, labelDy: -54 };
    segments[`${station.id}_rl_skip_bypass`] = { curve: 48, labelDx: 0, labelDy: 62 };
  });

  for (const segment of scenario.track_segments) {
    if (segment.kind !== "rope") continue;
    const from = nodes[segment.from_node_id];
    const to = nodes[segment.to_node_id];
    if (!from || !to) continue;
    segments[segment.id] = {
      curve: segment.id.includes("_lr") ? -12 : 12,
      labelDx: from.x < to.x ? -4 : -52,
      labelDy: segment.id.includes("_lr") ? -18 : 28,
    };
  }

  return {
    viewBox: `0 0 ${width} 620`,
    nodes,
    segments,
  };
}

function addLeftTerminal(
  nodes: Record<string, LayoutPoint>,
  station: Station,
  x: number,
  topY: number,
  bottomY: number,
  platformTopY: number,
  platformBottomY: number,
) {
  nodes[`${station.id}_exit_lr`] = { x: x + 54, y: topY, labelDx: -34, labelDy: -18 };
  nodes[`${station.id}_platform_exit`] = { x, y: platformTopY, labelDx: -70, labelDy: -10 };
  nodes[`${station.id}_platform_entry`] = { x, y: platformBottomY, labelDx: -72, labelDy: 18 };
  nodes[`${station.id}_entry_rl`] = { x: x + 54, y: bottomY, labelDx: -34, labelDy: 38 };
}

function addRightTerminal(
  nodes: Record<string, LayoutPoint>,
  station: Station,
  x: number,
  topY: number,
  bottomY: number,
  platformTopY: number,
  platformBottomY: number,
) {
  nodes[`${station.id}_entry_lr`] = { x: x - 54, y: topY, labelDx: 10, labelDy: -18 };
  nodes[`${station.id}_platform_entry`] = { x, y: platformTopY, labelDx: 12, labelDy: -10 };
  nodes[`${station.id}_platform_exit`] = { x, y: platformBottomY, labelDx: 12, labelDy: 18 };
  nodes[`${station.id}_exit_rl`] = { x: x - 54, y: bottomY, labelDx: 10, labelDy: 38 };
}

function addMiddleStation(
  nodes: Record<string, LayoutPoint>,
  station: Station,
  x: number,
  topY: number,
  bottomY: number,
  platformTopY: number,
  platformBottomY: number,
) {
  nodes[`${station.id}_entry_lr`] = { x: x - 76, y: topY, labelDx: -40, labelDy: -26 };
  nodes[`${station.id}_service_approach_lr`] = { x: x - 40, y: topY - 36 };
  nodes[`${station.id}_platform_entry_lr`] = { x: x - 18, y: platformTopY, labelDx: -36, labelDy: -24 };
  nodes[`${station.id}_platform_exit_lr`] = { x: x + 18, y: platformTopY, labelDx: -4, labelDy: -24 };
  nodes[`${station.id}_service_accelerate_lr`] = { x: x + 40, y: topY - 36 };
  nodes[`${station.id}_exit_lr`] = { x: x + 76, y: topY, labelDx: 8, labelDy: -26 };

  nodes[`${station.id}_entry_rl`] = { x: x + 76, y: bottomY, labelDx: 8, labelDy: 36 };
  nodes[`${station.id}_service_approach_rl`] = { x: x + 40, y: bottomY + 36 };
  nodes[`${station.id}_platform_entry_rl`] = { x: x + 18, y: platformBottomY, labelDx: -2, labelDy: 42 };
  nodes[`${station.id}_platform_exit_rl`] = { x: x - 18, y: platformBottomY, labelDx: -38, labelDy: 42 };
  nodes[`${station.id}_service_accelerate_rl`] = { x: x - 40, y: bottomY + 36 };
  nodes[`${station.id}_exit_rl`] = { x: x - 76, y: bottomY, labelDx: -44, labelDy: 36 };
}

function addTerminalSegmentHints(segments: Record<string, SegmentStyleHint>, stationId: string, side: "left" | "right") {
  const sign = side === "left" ? -1 : 1;
  segments[`${stationId}_turnaround_decelerate`] = { labelDx: 36 * sign, labelDy: side === "left" ? 20 : -18 };
  segments[`${stationId}_turnaround_platform`] = { labelDx: 50 * sign, labelDy: 0 };
  segments[`${stationId}_turnaround_accelerate`] = { labelDx: 36 * sign, labelDy: side === "left" ? -18 : 20 };
}

function circularSkipStopLayout(scenario: Scenario): ScenarioLayout {
  const stations = scenario.stations.filter((station) => station.kind === "service");
  if (stations.length < 3) return linearSkipStopLayout(scenario);

  const width = 900;
  const height = 760;
  const center = { x: width / 2, y: height / 2 };
  const radius = 250;
  const nodes: Record<string, LayoutPoint> = {};
  const segments: Record<string, SegmentStyleHint> = {};

  stations.forEach((station, index) => {
    const angle = -Math.PI / 2 + (2 * Math.PI * index) / stations.length;
    const stationGeometry = addCircularStation(nodes, station, center, radius, angle);
    segments[`${station.id}_cw_skip_bypass`] = {
      controlDx: stationGeometry.radial.x * 46,
      controlDy: stationGeometry.radial.y * 46,
      labelDx: stationGeometry.radial.x * 22,
      labelDy: stationGeometry.radial.y * 22,
    };
  });

  for (const segment of scenario.track_segments) {
    if (segment.kind !== "rope") continue;
    segments[segment.id] = { labelDx: 0, labelDy: -16 };
  }

  return {
    viewBox: `0 0 ${width} ${height}`,
    nodes,
    segments,
  };
}

function addCircularStation(
  nodes: Record<string, LayoutPoint>,
  station: Station,
  center: { x: number; y: number },
  radius: number,
  angle: number,
) {
  const radial = { x: Math.cos(angle), y: Math.sin(angle) };
  const tangent = { x: -Math.sin(angle), y: Math.cos(angle) };
  const inward = { x: -radial.x, y: -radial.y };
  const base = {
    x: center.x + radial.x * radius,
    y: center.y + radial.y * radius,
  };
  const labelDx = radial.x * 34;
  const labelDy = radial.y * 34;

  nodes[`${station.id}_entry_cw`] = {
    x: base.x - tangent.x * 72,
    y: base.y - tangent.y * 72,
    labelDx,
    labelDy,
  };
  nodes[`${station.id}_service_approach_cw`] = {
    x: base.x - tangent.x * 44 + inward.x * 24,
    y: base.y - tangent.y * 44 + inward.y * 24,
  };
  nodes[`${station.id}_platform_entry_cw`] = {
    x: base.x - tangent.x * 18 + inward.x * 54,
    y: base.y - tangent.y * 18 + inward.y * 54,
    labelDx,
    labelDy,
  };
  nodes[`${station.id}_platform_exit_cw`] = {
    x: base.x + tangent.x * 18 + inward.x * 54,
    y: base.y + tangent.y * 18 + inward.y * 54,
    labelDx,
    labelDy,
  };
  nodes[`${station.id}_service_accelerate_cw`] = {
    x: base.x + tangent.x * 44 + inward.x * 24,
    y: base.y + tangent.y * 44 + inward.y * 24,
  };
  nodes[`${station.id}_exit_cw`] = {
    x: base.x + tangent.x * 72,
    y: base.y + tangent.y * 72,
    labelDx,
    labelDy,
  };

  return { radial, tangent, inward, base };
}
