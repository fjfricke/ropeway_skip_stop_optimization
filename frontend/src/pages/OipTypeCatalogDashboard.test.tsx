import { expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { ReactNode } from "react";
import type { OptimizationCampaignSnapshot, OptimizationTrialSnapshot } from "../optimizationTypes";
vi.mock("../App", () => ({ AppLink: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a> }));
import OipTypeCatalogDashboard, { PhaseReferences } from "./OipTypeCatalogDashboard";

it("keeps K62 comparison observations distinct from planned K50 results", () => {
  const trial: OptimizationTrialSnapshot = {
    trial_id: "f2_mix_0_25_25_k50", policy_id: "f2", available_fleet_count: 50,
    family: "f2", status: "planned", demand_total: 2266, events: [],
    fixed_type_counts: { all_stop: 0, bd: 25, ce: 25 },
    comparison_trial_id: "f2_mix_0_31_31_k62",
  };
  const campaign: OptimizationCampaignSnapshot = {
    schema_version: 1, campaign_id: "k50", status: "prepared", sequence: 1,
    k_values: [50], trial_count: 15, completed_trial_count: 0,
    study_variant: "fleet_sensitivity", headway_contract: "geometric_shared_entry_exit_v1",
    reference_runs: {}, trials: [trial],
    comparison_campaign: {
      campaign_id: "k62", fleet_count: 62, role: "display_only_previous_fleet",
      trials: [{ ...trial, trial_id: "f2_mix_0_31_31_k62", available_fleet_count: 62, status: "complete", served: 2266, run_campaign_id: "k62_f2" }],
    },
  };
  const html = renderToStaticMarkup(<OipTypeCatalogDashboard campaign={campaign} />);
  expect(html).toContain("Bedient K50");
  expect(html).toContain("Bedient K62 · Vergleich");
  expect(html).toContain("ohne frühen Referenzabbruch");
  expect(html).toContain("keine neue K50-Kalibrierung");
  expect(html).toContain("25× bd · 25× ce");
  expect(html).toContain('<td>—</td><td>2.266');
  expect(html).toContain('href="/optimization/k62_f2"');
  expect(html).not.toContain("All-Stop-Referenzen");
  expect(html).not.toContain("0 %");
});

it("shows supplementary phase references without inventing values or global optimality", () => {
  const references = { status: "prepared", reference_runs: {
    f2: { status: "planned", fixed_k: 50, demand_total: 2266 },
    f3: { status: "complete", fixed_k: 50, demand_total: 5430, served: 4000, served_upper_bound: 4200, proven_optimal: false },
  }};
  const html = renderToStaticMarkup(<PhaseReferences references={references} />);
  expect(html).toContain("freie gemeinsame Phase");
  expect(html).toContain("Keine neue Nmax-Kalibrierung");
  expect(html).toContain('<td>2.266</td><td>—</td><td>—</td>');
  expect(html).toContain("Geprüfte Referenzlösung");
  expect(html).not.toContain("Optimal für regelmäßige Flotte");
});
