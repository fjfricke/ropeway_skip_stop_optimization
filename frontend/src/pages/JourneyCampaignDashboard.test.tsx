import { expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import JourneyCampaignDashboard from "./JourneyCampaignDashboard";
import { THESIS_CONTRACT_ID } from "../thesisContract";

it("shows native versus confirmed values, missing bounds and live detail links", () => {
  const html = renderToStaticMarkup(<JourneyCampaignDashboard campaign={{schema_version: 1, campaign_id: 'journey', status: 'running', sequence: 1, trials: [], journey_jobs: [
    {id: 'test', family: 'f2', k: 20, kind: 'relative', mode: 'skip_stop', demand: 50,
     status: 'running', native_incumbent: 123, validated_objective: null, lower_bound: null, gap: null,
     detail_url: '/thesis?run=test'},
  ]}} />);
  expect(html).toContain('Native incumbent');
  expect(html).toContain('Confirmed Journey Time');
  expect(html).toContain('123');
  expect(html).toContain('href="/thesis?run=test"');
  expect(html).not.toContain('0.00%');
  expect(html).toContain('half the K30');
  expect(THESIS_CONTRACT_ID).toContain('v3');
});
