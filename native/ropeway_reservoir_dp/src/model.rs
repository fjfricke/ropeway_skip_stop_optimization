use crate::domain::{Domain, ResourceUsage, RouteOption};
use crate::temporal::TemporalNetwork;
use rpid::{Bound, Dominance, Dp, OptimizationMode};
use serde::Serialize;
use std::hash::{Hash, Hasher};

const KIND_SHIFT: u64 = 60;
const FIELD_MASK: u64 = 0xffff;
const OBJECTIVE_SCALE: i32 = 1_000;
const ONBOARD_PROGRESS_WEIGHT: i32 = 10;

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize)]
pub struct Label(pub u64);

impl Label {
    fn make(kind: u64, a: usize, b: usize) -> Self {
        assert!(a <= FIELD_MASK as usize && b <= FIELD_MASK as usize);
        Self((kind << KIND_SHIFT) | (a as u64) | ((b as u64) << 16))
    }

    pub fn kind(self) -> u8 {
        (self.0 >> KIND_SHIFT) as u8
    }

    pub fn a(self) -> usize {
        (self.0 & FIELD_MASK) as usize
    }

    pub fn b(self) -> usize {
        ((self.0 >> 16) & FIELD_MASK) as usize
    }

    fn fleet(k: usize) -> Self {
        Self::make(1, k, 0)
    }
    fn route(option: usize, positive_wait: bool) -> Self {
        Self::make(2, option, usize::from(positive_wait))
    }
    fn insert(position: usize) -> Self {
        Self::make(3, position, 0)
    }
    fn board(group: usize, amount: usize) -> Self {
        Self::make(4, group, amount)
    }
    fn commit() -> Self {
        Self::make(5, 0, 0)
    }
    fn return_to_port() -> Self {
        Self::make(6, 0, 0)
    }
    fn pattern(mask: usize, group_size: usize) -> Self {
        Self::make(7, mask, group_size)
    }
    fn finish() -> Self {
        Self::make(8, 0, 0)
    }
    fn close_pattern_group() -> Self {
        Self::make(9, 0, 0)
    }
}

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
struct TimeExpr {
    variable: usize,
    offset: i64,
}

impl TimeExpr {
    fn before_or_equal(self, other: Self, network: &mut TemporalNetwork) -> Option<()> {
        // self.var + self.offset <= other.var + other.offset
        network.add_constraint(
            other.variable,
            self.variable,
            other.offset.checked_sub(self.offset)?,
        )
    }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
struct Interval {
    start: TimeExpr,
    end: TimeExpr,
    owner: u32,
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
enum CabinStatus {
    Active,
    Returned,
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
struct CabinState {
    status: CabinStatus,
    state: usize,
    visit: usize,
    time: usize,
    dispatch_time: usize,
    onboard: Vec<i32>,
    boarded_total: i32,
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
enum Phase {
    FleetChoice,
    Done,
    DispatchInsert {
        interval: Interval,
    },
    Visit,
    Insert {
        cabin: usize,
        option: usize,
        next_time: usize,
        intervals: Vec<(usize, Interval)>,
        cursor: usize,
    },
    Board {
        cabin: usize,
        option: usize,
        next_time: usize,
        groups: Vec<usize>,
        cursor: usize,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct State {
    phase: Phase,
    selected_fleet: Option<usize>,
    cabins: Vec<CabinState>,
    remaining: Vec<i32>,
    network: TemporalNetwork,
    orders: Vec<Vec<Interval>>,
    patterns: Vec<Option<u64>>,
    current_pattern: Option<u64>,
}

impl Hash for State {
    fn hash<H: Hasher>(&self, state: &mut H) {
        self.phase.hash(state);
        self.selected_fleet.hash(state);
        self.cabins.hash(state);
        self.remaining.hash(state);
        self.network.hash(state);
        self.orders.hash(state);
        self.patterns.hash(state);
        self.current_pattern.hash(state);
    }
}

#[derive(Clone)]
pub struct SymbolicVisits {
    pub domain: Domain,
    options_by_state: Vec<Vec<usize>>,
    demand_by_origin: Vec<Vec<usize>>,
    total_demand: i32,
    pattern_groups: bool,
    minimum_arrival: Vec<Vec<Option<i64>>>,
}

#[derive(Debug, Serialize)]
pub struct VisitWitness {
    pub option: usize,
    pub start: i64,
    pub wait: i64,
}

#[derive(Debug, Serialize)]
pub struct BoardWitness {
    pub cabin: usize,
    pub visit: usize,
    pub demand: usize,
    pub amount: i32,
}

#[derive(Debug, Serialize)]
pub struct PlanWitness {
    pub selected_fleet: usize,
    pub served: i32,
    pub visits: Vec<Vec<VisitWitness>>,
    pub returns: Vec<i64>,
    pub boards: Vec<BoardWitness>,
    pub pattern_masks: Vec<Option<u64>>,
}

impl SymbolicVisits {
    pub fn new(domain: Domain) -> Result<Self, String> {
        domain.validate()?;
        if domain.available_fleet > FIELD_MASK as usize
            || domain.options.len() > FIELD_MASK as usize
            || domain.demands.len() > FIELD_MASK as usize
        {
            return Err("domain exceeds transition label limits".into());
        }
        let total_demand: i32 = domain.demands.iter().map(|demand| demand.count).sum();
        total_demand
            .checked_mul(OBJECTIVE_SCALE)
            .ok_or("scaled objective exceeds the RPID integer range")?;
        let mut demand_by_origin = domain.demand_by_origin();
        for groups in &mut demand_by_origin {
            groups.sort_by_key(|index| {
                let demand = &domain.demands[*index];
                (demand.release, demand.destination, *index)
            });
        }
        let minimum_arrival = Self::minimum_arrival_offsets(&domain);
        Ok(Self {
            options_by_state: domain.options_by_state(),
            demand_by_origin,
            total_demand,
            domain,
            pattern_groups: false,
            minimum_arrival,
        })
    }

    pub fn new_pattern_groups(domain: Domain) -> Result<Self, String> {
        if domain.stations.len() > 16 {
            return Err("whole-trip pattern encoding supports at most 16 stations".into());
        }
        let mut result = Self::new(domain)?;
        result.pattern_groups = true;
        Ok(result)
    }

    fn activate_cabin(&self, state: &State) -> Option<(State, i32, Label)> {
        let cabin = state.cabins.len();
        if cabin >= self.domain.available_fleet {
            return None;
        }
        let mut successor = state.clone();
        let time = successor
            .network
            .add_timepoint(self.domain.dispatch_start, self.domain.dispatch_end)?;
        if let Some(previous) = successor.cabins.last() {
            successor
                .network
                .add_constraint(time, previous.dispatch_time, -1)?;
        }
        let interval = Interval {
            start: TimeExpr {
                variable: time,
                offset: 0,
            },
            end: TimeExpr {
                variable: time,
                offset: 1,
            },
            owner: (cabin as u32) << 16,
        };
        successor.cabins.push(CabinState {
            status: CabinStatus::Active,
            state: self.domain.entry_state,
            visit: 0,
            time,
            dispatch_time: time,
            onboard: vec![0; self.domain.stations.len()],
            boarded_total: 0,
        });
        successor.patterns.push(successor.current_pattern);
        successor.selected_fleet = Some(cabin + 1);
        successor.phase = Phase::DispatchInsert { interval };
        Some((successor, 0, Label::fleet(cabin + 1)))
    }

    fn state_resource(&self, state: usize) -> usize {
        self.domain.resources.len() + state
    }

    fn station_at_state(&self, state: usize) -> usize {
        self.options_by_state[state]
            .first()
            .map(|option| self.domain.options[*option].station)
            .unwrap_or(0)
    }

    fn minimum_arrival_offsets(domain: &Domain) -> Vec<Vec<Option<i64>>> {
        let state_count = domain.states.len();
        let station_count = domain.stations.len();
        let mut result = vec![vec![None; station_count]; state_count];
        for (destination, _) in domain.stations.iter().enumerate() {
            let mut distance = vec![None; state_count];
            for _ in 0..state_count {
                let mut changed = false;
                for state in 0..state_count {
                    let best = domain
                        .options
                        .iter()
                        .filter(|option| option.from_state == state)
                        .filter_map(|option| {
                            if option.station == destination {
                                if option.stop {
                                    option.platform_entry
                                } else {
                                    None
                                }
                            } else {
                                distance[option.to_state]
                                    .and_then(|tail| option.duration.checked_add(tail))
                            }
                        })
                        .min();
                    if let Some(best) = best
                        && distance[state].is_none_or(|current| best < current)
                    {
                        distance[state] = Some(best);
                        changed = true;
                    }
                }
                if !changed {
                    break;
                }
            }
            for state in 0..state_count {
                result[state][destination] = distance[state];
            }
        }
        result
    }

    /// Search guidance expressed as a state potential.  Transition weights use
    /// P(next)-P(current), so the potential cancels on every complete path.
    fn guidance_potential(&self, state: &State) -> i32 {
        let station_count = self.domain.stations.len();
        state
            .cabins
            .iter()
            .filter(|cabin| cabin.status == CabinStatus::Active)
            .map(|cabin| {
                let visit_progress = (cabin.visit % station_count) as i32;
                let current_station = self.station_at_state(cabin.state);
                let onboard_progress = cabin
                    .onboard
                    .iter()
                    .enumerate()
                    .map(|(destination, amount)| {
                        let distance =
                            (destination + station_count - current_station) % station_count;
                        // Reward a commitment only after the cabin has reached
                        // the destination state and its next STOP discharges it.
                        // Rewarding immediately at boarding overwhelms beams with
                        // mutually different load splits that never return.
                        let progress = usize::from(distance == 0);
                        amount * progress as i32 * ONBOARD_PROGRESS_WEIGHT
                    })
                    .sum::<i32>();
                visit_progress + onboard_progress
            })
            .sum()
    }

    fn guided_weight(&self, state: &State, successor: &State, reward: i32) -> i32 {
        reward * OBJECTIVE_SCALE + self.guidance_potential(successor)
            - self.guidance_potential(state)
    }

    fn scheduled_cabin(&self, state: &State) -> Option<usize> {
        state
            .cabins
            .iter()
            .enumerate()
            .filter(|(_, cabin)| cabin.status == CabinStatus::Active)
            // Construct one complete trip at a time.  This is only a decision
            // ordering: every resource interval can still be inserted before,
            // between, or after intervals of previously constructed cabins.
            // Therefore physical overtaking and every feasible resource order
            // remain representable.
            .min_by_key(|(id, _)| *id)
            .map(|(id, _)| id)
    }

    fn expression(
        &self,
        current: usize,
        next: usize,
        option: &RouteOption,
        offset: i64,
        wait: i32,
    ) -> Option<TimeExpr> {
        match wait {
            0 => Some(TimeExpr {
                variable: current,
                offset,
            }),
            1 => Some(TimeExpr {
                variable: next,
                offset: offset.checked_sub(option.duration)?,
            }),
            _ => None,
        }
    }

    fn interval_for_usage(
        &self,
        current: usize,
        next: usize,
        option: &RouteOption,
        usage: &ResourceUsage,
        owner: u32,
    ) -> Option<Interval> {
        Some(Interval {
            start: self.expression(current, next, option, usage.enter_offset, usage.enter_wait)?,
            end: self.expression(current, next, option, usage.clear_offset, usage.clear_wait)?,
            owner,
        })
    }

    fn select_route(
        &self,
        state: &State,
        cabin: usize,
        option_index: usize,
        positive_wait: bool,
    ) -> Option<(State, i32, Label)> {
        let option = &self.domain.options[option_index];
        let current_cabin = &state.cabins[cabin];
        if option.from_state != current_cabin.state || current_cabin.visit >= self.domain.max_visits
        {
            return None;
        }
        if let Some(mask) = state.patterns[cabin]
            && (((mask >> option.station) & 1) == 1) != option.stop
        {
            return None;
        }
        let station = option.station;
        let alighting = current_cabin.onboard[station];
        if alighting > 0 && !option.stop {
            return None;
        }
        if positive_wait && (!option.stop || option.maximum_wait == 0) {
            return None;
        }
        let mut successor = state.clone();
        let current = current_cabin.time;
        let next = successor
            .network
            .add_timepoint(0, self.domain.operational_end)?;
        if positive_wait {
            successor.network.add_constraint(
                next,
                current,
                option.duration.checked_add(1)?.checked_neg()?,
            )?;
            successor.network.add_constraint(
                current,
                next,
                option.duration.checked_add(option.maximum_wait)?,
            )?;
            let exit = option.platform_exit?;
            successor.network.add_constraint(
                current,
                0,
                exit.checked_sub(self.domain.earliest_positive_wait)?,
            )?;
        } else {
            successor
                .network
                .add_equality(current, next, option.duration)?;
        }
        if alighting > 0 {
            let entry = option.platform_entry?;
            successor.network.add_constraint(
                0,
                current,
                self.domain.service_end.checked_sub(entry)?,
            )?;
            successor.cabins[cabin].onboard[station] = 0;
        }
        successor.cabins[cabin].state = option.to_state;
        successor.cabins[cabin].visit += 1;
        successor.cabins[cabin].time = next;

        let owner = ((cabin as u32) << 16) | current_cabin.visit as u32;
        let mut intervals = Vec::with_capacity(option.usages.len() + 1);
        for usage in &option.usages {
            intervals.push((
                usage.resource,
                self.interval_for_usage(current, next, option, usage, owner)?,
            ));
        }
        intervals.push((
            self.state_resource(option.to_state),
            Interval {
                start: TimeExpr {
                    variable: next,
                    offset: 0,
                },
                end: TimeExpr {
                    variable: next,
                    offset: 1,
                },
                owner,
            },
        ));
        successor.phase = Phase::Insert {
            cabin,
            option: option_index,
            next_time: next,
            intervals,
            cursor: 0,
        };
        // Credit service only at the mandatory, timely destination stop.  This
        // guides primal search toward completed rides instead of accumulating
        // commitments that can no longer all be discharged before the horizon.
        Some((
            successor,
            alighting,
            Label::route(option_index, positive_wait),
        ))
    }

    fn insert_successors(
        &self,
        state: &State,
        resource: usize,
        interval: &Interval,
    ) -> Vec<(State, i32, Label)> {
        let mut result = Vec::new();
        let count = state.orders[resource].len();
        for position in 0..=count {
            let mut successor = state.clone();
            if position > 0
                && successor.orders[resource][position - 1]
                    .end
                    .before_or_equal(interval.start, &mut successor.network)
                    .is_none()
            {
                continue;
            }
            if position < count
                && interval
                    .end
                    .before_or_equal(
                        successor.orders[resource][position].start,
                        &mut successor.network,
                    )
                    .is_none()
            {
                continue;
            }
            successor.orders[resource].insert(position, interval.clone());
            if let Phase::Insert { cursor, .. } = &mut successor.phase {
                *cursor += 1;
            }
            result.push((successor, 0, Label::insert(position)));
        }
        result
    }

    fn advance_after_inserts(
        &self,
        state: &State,
        cabin: usize,
        option: usize,
        next_time: usize,
    ) -> (State, i32, Label) {
        let mut successor = state.clone();
        let station = self.domain.options[option].station;
        let groups = if self.domain.options[option].stop {
            self.demand_by_origin[station].clone()
        } else {
            Vec::new()
        };
        successor.phase = Phase::Board {
            cabin,
            option,
            next_time,
            groups,
            cursor: 0,
        };
        (successor, 0, Label::commit())
    }

    fn board_successors(
        &self,
        state: &State,
        cabin: usize,
        option_index: usize,
        next_time: usize,
        group_index: usize,
    ) -> Vec<(State, i32, Label)> {
        let option = &self.domain.options[option_index];
        let demand = &self.domain.demands[group_index];
        let load: i32 = state.cabins[cabin].onboard.iter().sum();
        let maximum = state.remaining[group_index].min(self.domain.capacity - load);
        let mut result = Vec::new();
        for amount in (0..=maximum).rev() {
            let mut successor = state.clone();
            if amount > 0 {
                let departure_offset = option
                    .platform_exit
                    .unwrap()
                    .checked_sub(option.duration)
                    .unwrap();
                if successor
                    .network
                    .add_constraint(
                        next_time,
                        0,
                        departure_offset.checked_sub(demand.release).unwrap(),
                    )
                    .is_none()
                {
                    continue;
                }
                let Some(minimum_arrival) =
                    self.minimum_arrival[option.to_state][demand.destination]
                else {
                    continue;
                };
                if successor
                    .network
                    .add_constraint(
                        0,
                        next_time,
                        self.domain
                            .service_end
                            .checked_sub(minimum_arrival)
                            .unwrap(),
                    )
                    .is_none()
                {
                    continue;
                }
                successor.remaining[group_index] -= amount;
                successor.cabins[cabin].onboard[demand.destination] += amount;
                successor.cabins[cabin].boarded_total += amount;
            }
            if let Phase::Board { cursor, .. } = &mut successor.phase {
                *cursor += 1;
            }
            result.push((successor, 0, Label::board(group_index, amount as usize)));
        }
        result
    }

    fn return_successor(&self, state: &State, cabin: usize) -> Option<(State, i32, Label)> {
        let current = &state.cabins[cabin];
        if current.visit == 0
            || current.state != self.domain.entry_state
            || current.boarded_total == 0
            || current.onboard.iter().any(|amount| *amount != 0)
        {
            return None;
        }
        let mut successor = state.clone();
        successor.network.add_constraint(
            current.time,
            0,
            self.domain.return_start.checked_neg()?,
        )?;
        successor.cabins[cabin].status = CabinStatus::Returned;
        if successor
            .cabins
            .iter()
            .all(|candidate| candidate.status == CabinStatus::Returned)
        {
            successor.phase = Phase::FleetChoice;
        }
        Some((successor, 0, Label::return_to_port()))
    }

    pub fn replay(&self, labels: &[Label]) -> Result<(State, PlanWitness), String> {
        let mut state = self.get_target();
        let mut visits: Vec<Vec<(usize, usize, usize)>> = Vec::new();
        let mut returns: Vec<Option<usize>> = Vec::new();
        let mut boards = Vec::new();
        for label in labels {
            let before = state.clone();
            let successors = self.get_successors(&state).into_iter().collect::<Vec<_>>();
            let (next, _reward, _) = successors
                .into_iter()
                .find(|(_, _, candidate)| candidate == label)
                .ok_or_else(|| format!("transition {} is not applicable", label.0))?;
            match label.kind() {
                1 => {
                    visits.push(Vec::new());
                    returns.push(None);
                }
                2 => {
                    let cabin = self.scheduled_cabin(&before).ok_or("route without cabin")?;
                    let old = &before.cabins[cabin];
                    let new = &next.cabins[cabin];
                    visits[cabin].push((label.a(), old.time, new.time));
                }
                4 if label.b() > 0 => {
                    let (cabin, visit) = match before.phase {
                        Phase::Board { cabin, .. } => (cabin, before.cabins[cabin].visit - 1),
                        _ => return Err("board label outside board phase".into()),
                    };
                    boards.push(BoardWitness {
                        cabin,
                        visit,
                        demand: label.a(),
                        amount: label.b() as i32,
                    });
                }
                6 => {
                    let cabin = self
                        .scheduled_cabin(&before)
                        .ok_or("return without cabin")?;
                    returns[cabin] = Some(before.cabins[cabin].time);
                }
                _ => {}
            }
            state = next;
        }
        if self.get_base_cost(&state).is_none() {
            return Err("transition sequence is not a complete plan".into());
        }
        let schedule = state
            .network
            .latest_schedule()
            .ok_or("complete temporal network has no schedule")?;
        let mut output_visits = Vec::new();
        for cabin_visits in visits {
            output_visits.push(
                cabin_visits
                    .into_iter()
                    .map(|(option, start, next)| VisitWitness {
                        option,
                        start: schedule[start],
                        wait: schedule[next]
                            - schedule[start]
                            - self.domain.options[option].duration,
                    })
                    .collect(),
            );
        }
        let pattern_masks = state.patterns.clone();
        let served = self.total_demand - state.remaining.iter().sum::<i32>();
        Ok((
            state,
            PlanWitness {
                selected_fleet: output_visits.len(),
                served,
                visits: output_visits,
                returns: returns
                    .into_iter()
                    .map(|variable| schedule[variable.expect("complete plan return")])
                    .collect(),
                boards,
                pattern_masks,
            },
        ))
    }
}

impl Dp for SymbolicVisits {
    type State = State;
    type CostType = i32;
    type Label = Label;

    fn get_target(&self) -> Self::State {
        State {
            phase: Phase::FleetChoice,
            selected_fleet: Some(0),
            cabins: Vec::new(),
            remaining: self
                .domain
                .demands
                .iter()
                .map(|demand| demand.count)
                .collect(),
            network: TemporalNetwork::new(),
            orders: vec![Vec::new(); self.domain.resources.len() + self.domain.states.len()],
            patterns: Vec::new(),
            current_pattern: None,
        }
    }

    fn get_successors(
        &self,
        state: &Self::State,
    ) -> impl IntoIterator<Item = (Self::State, Self::CostType, Self::Label)> {
        let mut result = Vec::new();
        match &state.phase {
            Phase::FleetChoice => {
                let mut finished = state.clone();
                finished.phase = Phase::Done;
                result.push((finished, 0, Label::finish()));
                if self.pattern_groups {
                    if state.current_pattern.is_some() {
                        if let Some(successor) = self.activate_cabin(state) {
                            result.push(successor);
                        }
                        let mut closed = state.clone();
                        closed.current_pattern = None;
                        result.push((closed, 0, Label::close_pattern_group()));
                    } else if state.cabins.len() < self.domain.available_fleet {
                        let pattern_count = 1usize << self.domain.stations.len();
                        for mask in 0..pattern_count {
                            let serves_a_ride = self.domain.demands.iter().any(|demand| {
                                ((mask >> demand.origin) & 1) == 1
                                    && ((mask >> demand.destination) & 1) == 1
                            });
                            if !serves_a_ride {
                                continue;
                            }
                            let mut successor = state.clone();
                            successor.current_pattern = Some(mask as u64);
                            result.push((successor, 0, Label::pattern(mask, 0)));
                        }
                    }
                } else if let Some(successor) = self.activate_cabin(state) {
                    result.push(successor);
                }
            }
            Phase::Done => {}
            Phase::DispatchInsert { interval } => {
                let resource = self.state_resource(self.domain.entry_state);
                for position in 0..=state.orders[resource].len() {
                    let mut successor = state.clone();
                    if position > 0
                        && successor.orders[resource][position - 1]
                            .end
                            .before_or_equal(interval.start, &mut successor.network)
                            .is_none()
                    {
                        continue;
                    }
                    if position < state.orders[resource].len()
                        && interval
                            .end
                            .before_or_equal(
                                successor.orders[resource][position].start,
                                &mut successor.network,
                            )
                            .is_none()
                    {
                        continue;
                    }
                    successor.orders[resource].insert(position, interval.clone());
                    successor.phase = Phase::Visit;
                    result.push((successor, 0, Label::insert(position)));
                }
            }
            Phase::Visit => {
                if let Some(cabin) = self.scheduled_cabin(state) {
                    if let Some(successor) = self.return_successor(state, cabin) {
                        result.push(successor);
                    }
                    let current = &state.cabins[cabin];
                    let mut options = self.options_by_state[current.state].clone();
                    options.sort_by_key(|index| !self.domain.options[*index].stop);
                    for option in options {
                        if let Some(successor) = self.select_route(state, cabin, option, false) {
                            result.push(successor);
                        }
                        if let Some(successor) = self.select_route(state, cabin, option, true) {
                            result.push(successor);
                        }
                    }
                }
            }
            Phase::Insert {
                cabin,
                option,
                next_time,
                intervals,
                cursor,
            } => {
                if let Some((resource, interval)) = intervals.get(*cursor) {
                    result.extend(self.insert_successors(state, *resource, interval));
                } else {
                    result.push(self.advance_after_inserts(state, *cabin, *option, *next_time));
                }
            }
            Phase::Board {
                cabin,
                option,
                next_time,
                groups,
                cursor,
            } => {
                if let Some(group) = groups.get(*cursor) {
                    // Closing boarding early is equivalent to assigning zero to
                    // every remaining demand group.  Keeping it as one transition
                    // avoids burying the empty/partially loaded choice under a
                    // combinatorial number of bucket allocations.
                    let mut closed = state.clone();
                    closed.phase = Phase::Visit;
                    result.push((closed, 0, Label::commit()));
                    result
                        .extend(self.board_successors(state, *cabin, *option, *next_time, *group));
                } else {
                    let mut successor = state.clone();
                    successor.phase = Phase::Visit;
                    result.push((successor, 0, Label::commit()));
                }
            }
        }
        result
            .into_iter()
            .map(|(successor, reward, label)| {
                let weight = self.guided_weight(state, &successor, reward);
                (successor, weight, label)
            })
            .collect::<Vec<_>>()
    }

    fn get_base_cost(&self, state: &Self::State) -> Option<Self::CostType> {
        if state.phase == Phase::Done {
            Some(0)
        } else {
            None
        }
    }

    fn get_optimization_mode(&self) -> OptimizationMode {
        OptimizationMode::Maximization
    }
}

impl Dominance for SymbolicVisits {
    type State = State;
    type Key = State;

    fn get_key(&self, state: &Self::State) -> Self::Key {
        state.clone()
    }
}

impl Bound for SymbolicVisits {
    type State = State;
    type CostType = i32;

    fn get_dual_bound(&self, state: &Self::State) -> Option<Self::CostType> {
        if state.phase == Phase::Done {
            return Some(0);
        }
        let future_service = state.remaining.iter().sum::<i32>()
            + state
                .cabins
                .iter()
                .flat_map(|cabin| cabin.onboard.iter())
                .sum::<i32>();
        Some(future_service * OBJECTIVE_SCALE - self.guidance_potential(state))
    }

    fn get_global_dual_bound(&self) -> Option<Self::CostType> {
        Some(self.total_demand * OBJECTIVE_SCALE)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::{Demand, Resource};
    use rpid::prelude::{CabsParameters, SearchParameters};

    fn tiny_domain(demand: i32, waiting: i64) -> Domain {
        Domain {
            schema: "reservoir_symbolic_dp_domain_v1".into(),
            source_fingerprint: "test".into(),
            capacity: 2,
            available_fleet: 1,
            entry_state: 0,
            dispatch_start: 0,
            dispatch_end: 0,
            return_start: 0,
            service_end: 5,
            operational_end: 8,
            earliest_positive_wait: 0,
            states: vec!["A".into(), "B".into()],
            stations: vec!["A".into(), "B".into()],
            resources: vec![Resource {
                id: "rope".into(),
                minimum_headway: 1,
            }],
            options: vec![
                RouteOption {
                    id: "A_stop".into(),
                    from_state: 0,
                    to_state: 1,
                    station: 0,
                    stop: true,
                    duration: 2,
                    platform_entry: Some(0),
                    platform_exit: Some(1),
                    maximum_wait: waiting,
                    usages: vec![ResourceUsage {
                        resource: 0,
                        enter_offset: 0,
                        enter_wait: 0,
                        clear_offset: 1,
                        clear_wait: 0,
                    }],
                },
                RouteOption {
                    id: "A_skip".into(),
                    from_state: 0,
                    to_state: 1,
                    station: 0,
                    stop: false,
                    duration: 1,
                    platform_entry: None,
                    platform_exit: None,
                    maximum_wait: 0,
                    usages: vec![ResourceUsage {
                        resource: 0,
                        enter_offset: 0,
                        enter_wait: 0,
                        clear_offset: 1,
                        clear_wait: 0,
                    }],
                },
                RouteOption {
                    id: "B_stop".into(),
                    from_state: 1,
                    to_state: 0,
                    station: 1,
                    stop: true,
                    duration: 2,
                    platform_entry: Some(0),
                    platform_exit: Some(1),
                    maximum_wait: waiting,
                    usages: vec![ResourceUsage {
                        resource: 0,
                        enter_offset: 0,
                        enter_wait: 0,
                        clear_offset: 1,
                        clear_wait: 0,
                    }],
                },
                RouteOption {
                    id: "B_skip".into(),
                    from_state: 1,
                    to_state: 0,
                    station: 1,
                    stop: false,
                    duration: 1,
                    platform_entry: None,
                    platform_exit: None,
                    maximum_wait: 0,
                    usages: vec![ResourceUsage {
                        resource: 0,
                        enter_offset: 0,
                        enter_wait: 0,
                        clear_offset: 1,
                        clear_wait: 0,
                    }],
                },
            ],
            demands: vec![Demand {
                id: "g".into(),
                origin: 0,
                destination: 1,
                release: 0,
                count: demand,
            }],
            max_visits: 6,
        }
    }

    #[test]
    fn cabs_finds_complete_waiting_plan_and_variable_fleet() {
        let model = SymbolicVisits::new(tiny_domain(2, 2)).unwrap();
        let parameters = SearchParameters {
            quiet: true,
            time_limit: Some(5.0),
            ..Default::default()
        };
        let cabs = CabsParameters {
            initial_beam_width: 64,
            max_beam_width: Some(1024),
            keep_all_layers: true,
        };
        let mut solver = rpid::solvers::create_blind_cabs(model.clone(), parameters, cabs);
        let solution = solver.search();
        assert_eq!(solution.cost, Some(2 * OBJECTIVE_SCALE));
        let (_, witness) = model.replay(&solution.transitions).unwrap();
        assert_eq!(witness.selected_fleet, 1);
        assert_eq!(witness.served, 2);
        assert_eq!(witness.visits[0].len(), 2);
    }

    #[test]
    fn zero_fleet_is_a_complete_zero_service_plan() {
        let model = SymbolicVisits::new(tiny_domain(1, 0)).unwrap();
        let target = model.get_target();
        let zero = model
            .get_successors(&target)
            .into_iter()
            .find(|(_, _, label)| *label == Label::finish())
            .unwrap()
            .0;
        assert_eq!(model.get_base_cost(&zero), Some(0));
    }

    #[test]
    fn whole_trip_pattern_groups_find_required_stops() {
        let model = SymbolicVisits::new_pattern_groups(tiny_domain(2, 2)).unwrap();
        let parameters = SearchParameters {
            quiet: true,
            time_limit: Some(5.0),
            ..Default::default()
        };
        let cabs = CabsParameters {
            initial_beam_width: 128,
            max_beam_width: Some(2048),
            keep_all_layers: true,
        };
        let mut solver = rpid::solvers::create_blind_cabs(model.clone(), parameters, cabs);
        let solution = solver.search();
        assert_eq!(solution.cost, Some(2 * OBJECTIVE_SCALE));
        let (_, witness) = model.replay(&solution.transitions).unwrap();
        assert_eq!(witness.pattern_masks, vec![Some(3)]);
    }

    #[test]
    fn dual_search_does_not_treat_lazy_zero_fleet_as_optimal() {
        let model = SymbolicVisits::new(tiny_domain(2, 2)).unwrap();
        let parameters = SearchParameters {
            quiet: true,
            time_limit: Some(5.0),
            ..Default::default()
        };
        let cabs = CabsParameters {
            initial_beam_width: 64,
            max_beam_width: Some(1024),
            keep_all_layers: true,
        };
        let mut solver = rpid::solvers::create_cabs(model, parameters, cabs);
        let solution = solver.search();
        assert_eq!(solution.cost, Some(2 * OBJECTIVE_SCALE));
    }
}
