export interface LayoutPoint {
  x: number;
  y: number;
  labelDx?: number;
  labelDy?: number;
}

export interface SegmentStyleHint {
  curve?: number;
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
