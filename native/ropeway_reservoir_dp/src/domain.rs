use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Domain {
    pub schema: String,
    pub source_fingerprint: String,
    pub capacity: i32,
    pub available_fleet: usize,
    pub entry_state: usize,
    pub dispatch_start: i64,
    pub dispatch_end: i64,
    pub return_start: i64,
    pub service_end: i64,
    pub operational_end: i64,
    pub earliest_positive_wait: i64,
    pub states: Vec<String>,
    pub stations: Vec<String>,
    pub resources: Vec<Resource>,
    pub options: Vec<RouteOption>,
    pub demands: Vec<Demand>,
    pub max_visits: usize,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Resource {
    pub id: String,
    pub minimum_headway: i64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct RouteOption {
    pub id: String,
    pub from_state: usize,
    pub to_state: usize,
    pub station: usize,
    pub stop: bool,
    pub duration: i64,
    pub platform_entry: Option<i64>,
    pub platform_exit: Option<i64>,
    pub maximum_wait: i64,
    pub usages: Vec<ResourceUsage>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct ResourceUsage {
    pub resource: usize,
    pub enter_offset: i64,
    pub enter_wait: i32,
    pub clear_offset: i64,
    pub clear_wait: i32,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Demand {
    pub id: String,
    pub origin: usize,
    pub destination: usize,
    pub release: i64,
    pub count: i32,
}

impl Domain {
    pub fn validate(&self) -> Result<(), String> {
        if self.schema != "reservoir_symbolic_dp_domain_v1" {
            return Err("unsupported reservoir DP schema".into());
        }
        if self.capacity <= 0
            || self.available_fleet == 0
            || self.entry_state >= self.states.len()
            || self.states.len() != self.stations.len()
            || self.dispatch_start > self.dispatch_end
            || self.dispatch_end > self.operational_end
            || self.service_end > self.operational_end
            || self.max_visits == 0
        {
            return Err("invalid reservoir DP bounds".into());
        }
        let mut outgoing = vec![0usize; self.states.len()];
        for option in &self.options {
            if option.from_state >= self.states.len()
                || option.to_state >= self.states.len()
                || option.station >= self.stations.len()
                || option.duration <= 0
                || option.maximum_wait < 0
            {
                return Err("invalid route option".into());
            }
            if option.stop != option.platform_entry.is_some()
                || option.stop != option.platform_exit.is_some()
                || (!option.stop && option.maximum_wait != 0)
            {
                return Err("invalid STOP/SKIP phase data".into());
            }
            for usage in &option.usages {
                if usage.resource >= self.resources.len()
                    || !matches!(usage.enter_wait, 0 | 1)
                    || !matches!(usage.clear_wait, 0 | 1)
                {
                    return Err("unsupported resource expression".into());
                }
            }
            outgoing[option.from_state] += 1;
        }
        if outgoing.contains(&0) {
            return Err("state without a route option".into());
        }
        for demand in &self.demands {
            if demand.origin >= self.stations.len()
                || demand.destination >= self.stations.len()
                || demand.origin == demand.destination
                || demand.count < 0
                || demand.release < 0
                || demand.release > self.service_end
            {
                return Err("invalid demand".into());
            }
        }
        Ok(())
    }

    pub fn options_by_state(&self) -> Vec<Vec<usize>> {
        let mut result = vec![Vec::new(); self.states.len()];
        for (index, option) in self.options.iter().enumerate() {
            result[option.from_state].push(index);
        }
        result
    }

    pub fn demand_by_origin(&self) -> Vec<Vec<usize>> {
        let mut result = vec![Vec::new(); self.stations.len()];
        for (index, demand) in self.demands.iter().enumerate() {
            result[demand.origin].push(index);
        }
        result
    }

    pub fn stop_option_by_state(&self) -> HashMap<usize, usize> {
        self.options
            .iter()
            .enumerate()
            .filter(|(_, option)| option.stop)
            .map(|(index, option)| (option.from_state, index))
            .collect()
    }
}
