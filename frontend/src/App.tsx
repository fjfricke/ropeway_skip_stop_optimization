import { useEffect, useState } from "react";
import { ScenarioViewer } from "./components/ScenarioViewer";
import type { DiscreteScenario, MovementPlan, PassengerReplayResult, ReplayMetrics, Scenario } from "./types";

const SCENARIO_URL = "/scenarios/three_station_v0.json";
const DISCRETE_SCENARIO_URL = "/scenarios/three_station_v0__dt_0p5.json";
const MOVEMENT_PLAN_URL = "/scenarios/three_station_v0__dt_0p5__greedy_all_stop_movement_plan.json";
const PASSENGER_REPLAY_URL = "/scenarios/three_station_v0__dt_0p5__greedy_all_stop_passenger_replay.json";
const REPLAY_METRICS_URL = "/scenarios/three_station_v0__dt_0p5__greedy_all_stop_replay_metrics.json";

export default function App() {
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [discreteScenario, setDiscreteScenario] = useState<DiscreteScenario | null>(null);
  const [movementPlan, setMovementPlan] = useState<MovementPlan | null>(null);
  const [passengerReplay, setPassengerReplay] = useState<PassengerReplayResult | null>(null);
  const [replayMetrics, setReplayMetrics] = useState<ReplayMetrics | null>(null);
  const [discreteWarning, setDiscreteWarning] = useState<string | null>(null);
  const [movementPlanWarning, setMovementPlanWarning] = useState<string | null>(null);
  const [passengerReplayWarning, setPassengerReplayWarning] = useState<string | null>(null);
  const [replayMetricsWarning, setReplayMetricsWarning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadScenario() {
      try {
        const scenarioResponse = await fetch(SCENARIO_URL);
        if (!scenarioResponse.ok) {
          throw new Error(`Failed to load ${SCENARIO_URL}: ${scenarioResponse.status}`);
        }
        const data = (await scenarioResponse.json()) as Scenario;
        let discreteData: DiscreteScenario | null = null;
        let movementData: MovementPlan | null = null;
        let passengerReplayData: PassengerReplayResult | null = null;
        let replayMetricsData: ReplayMetrics | null = null;
        let discreteLoadWarning: string | null = null;
        let movementLoadWarning: string | null = null;
        let passengerReplayLoadWarning: string | null = null;
        let replayMetricsLoadWarning: string | null = null;

        try {
          const discreteResponse = await fetch(DISCRETE_SCENARIO_URL);
          if (discreteResponse.ok) {
            discreteData = (await discreteResponse.json()) as DiscreteScenario;
          } else {
            discreteLoadWarning = `Discrete overlay unavailable (${DISCRETE_SCENARIO_URL}: ${discreteResponse.status})`;
          }
        } catch (discreteLoadError) {
          discreteLoadWarning =
            discreteLoadError instanceof Error ? discreteLoadError.message : "Unknown discrete scenario load error";
        }

        try {
          const movementResponse = await fetch(MOVEMENT_PLAN_URL);
          if (movementResponse.ok) {
            movementData = (await movementResponse.json()) as MovementPlan;
          } else {
            movementLoadWarning = `Replay unavailable (${MOVEMENT_PLAN_URL}: ${movementResponse.status})`;
          }
        } catch (movementLoadError) {
          movementLoadWarning =
            movementLoadError instanceof Error ? movementLoadError.message : "Unknown movement plan load error";
        }

        try {
          const passengerReplayResponse = await fetch(PASSENGER_REPLAY_URL);
          if (passengerReplayResponse.ok) {
            passengerReplayData = (await passengerReplayResponse.json()) as PassengerReplayResult;
          } else {
            passengerReplayLoadWarning = `Passenger replay unavailable (${PASSENGER_REPLAY_URL}: ${passengerReplayResponse.status})`;
          }
        } catch (passengerReplayLoadError) {
          passengerReplayLoadWarning =
            passengerReplayLoadError instanceof Error ? passengerReplayLoadError.message : "Unknown passenger replay load error";
        }

        try {
          const replayMetricsResponse = await fetch(REPLAY_METRICS_URL);
          if (replayMetricsResponse.ok) {
            replayMetricsData = (await replayMetricsResponse.json()) as ReplayMetrics;
          } else {
            replayMetricsLoadWarning = `Replay metrics unavailable (${REPLAY_METRICS_URL}: ${replayMetricsResponse.status})`;
          }
        } catch (replayMetricsLoadError) {
          replayMetricsLoadWarning =
            replayMetricsLoadError instanceof Error ? replayMetricsLoadError.message : "Unknown replay metrics load error";
        }

        if (!cancelled) {
          setScenario(data);
          setDiscreteScenario(discreteData);
          setMovementPlan(movementData);
          setPassengerReplay(passengerReplayData);
          setReplayMetrics(replayMetricsData);
          setDiscreteWarning(discreteLoadWarning);
          setMovementPlanWarning(movementLoadWarning);
          setPassengerReplayWarning(passengerReplayLoadWarning);
          setReplayMetricsWarning(replayMetricsLoadWarning);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "Unknown scenario load error");
        }
      }
    }

    loadScenario();
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <main className="app-shell">
        <section className="load-state load-state--error">{error}</section>
      </main>
    );
  }

  if (!scenario) {
    return (
      <main className="app-shell">
        <section className="load-state">Loading scenario</section>
      </main>
    );
  }

  return (
    <ScenarioViewer
      scenario={scenario}
      discreteScenario={discreteScenario}
      movementPlan={movementPlan}
      passengerReplay={passengerReplay}
      replayMetrics={replayMetrics}
      discreteWarning={discreteWarning}
      movementPlanWarning={movementPlanWarning}
      passengerReplayWarning={passengerReplayWarning}
      replayMetricsWarning={replayMetricsWarning}
    />
  );
}
