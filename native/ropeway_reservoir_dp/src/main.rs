use ropeway_reservoir_dp::domain::Domain;
use ropeway_reservoir_dp::model::{Label, PlanWitness, SymbolicVisits};
use rpid::prelude::{CabsParameters, Search, SearchParameters};
use serde::Serialize;
use std::env;
use std::fs;
use std::path::PathBuf;

const OBJECTIVE_SCALE: i32 = 1_000;

#[derive(Serialize)]
struct Improvement {
    elapsed_seconds: f64,
    served: i32,
}

#[derive(Serialize)]
struct Output {
    schema: &'static str,
    engine: String,
    search_mode: String,
    source_fingerprint: String,
    status: String,
    served: Option<i32>,
    best_bound_served: Option<i32>,
    is_optimal: bool,
    is_infeasible: bool,
    time_limit_reached: bool,
    expanded: usize,
    generated: usize,
    elapsed_seconds: f64,
    improvements: Vec<Improvement>,
    labels: Vec<Label>,
    plan: Option<PlanWitness>,
}

struct Args {
    input: PathBuf,
    output: PathBuf,
    time_limit: f64,
    workers: usize,
    initial_beam_width: usize,
    max_beam_width: usize,
    keep_all_layers: bool,
    variant: String,
    search_mode: String,
}

fn parse_args() -> Result<Args, String> {
    let mut values = env::args().skip(1);
    let mut input = None;
    let mut output = None;
    let mut time_limit: f64 = 60.0;
    let mut workers = 1usize;
    let mut initial_beam_width = 64usize;
    let mut max_beam_width = 1024usize;
    let mut keep_all_layers = false;
    let mut variant = "symbolic_visits".to_string();
    let mut search_mode = "primal".to_string();
    while let Some(flag) = values.next() {
        let mut value = || {
            values
                .next()
                .ok_or_else(|| format!("missing value for {flag}"))
        };
        match flag.as_str() {
            "--input" => input = Some(PathBuf::from(value()?)),
            "--output" => output = Some(PathBuf::from(value()?)),
            "--time-limit" => time_limit = value()?.parse().map_err(|_| "invalid time limit")?,
            "--workers" => workers = value()?.parse().map_err(|_| "invalid worker count")?,
            "--initial-beam-width" => {
                initial_beam_width = value()?.parse().map_err(|_| "invalid initial beam width")?
            }
            "--max-beam-width" => {
                max_beam_width = value()?.parse().map_err(|_| "invalid maximum beam width")?
            }
            "--keep-all-layers" => {
                keep_all_layers = value()?.parse().map_err(|_| "invalid keep-all-layers")?
            }
            "--variant" => variant = value()?,
            "--search-mode" => search_mode = value()?,
            _ => return Err(format!("unknown argument {flag}")),
        }
    }
    if !time_limit.is_finite()
        || time_limit <= 0.0
        || workers == 0
        || initial_beam_width == 0
        || max_beam_width < initial_beam_width
    {
        return Err("invalid search parameters".into());
    }
    Ok(Args {
        input: input.ok_or("--input is required")?,
        output: output.ok_or("--output is required")?,
        time_limit,
        workers,
        initial_beam_width,
        max_beam_width,
        keep_all_layers,
        variant,
        search_mode,
    })
}

fn run() -> Result<(), String> {
    let args = parse_args()?;
    let domain: Domain = serde_json::from_slice(
        &fs::read(&args.input).map_err(|error| format!("cannot read input: {error}"))?,
    )
    .map_err(|error| format!("invalid input JSON: {error}"))?;
    let model = match args.variant.as_str() {
        "symbolic_visits" => SymbolicVisits::new(domain.clone())?,
        "pattern_groups" => SymbolicVisits::new_pattern_groups(domain.clone())?,
        _ => return Err("unsupported reservoir DP variant".into()),
    };
    let search_parameters = SearchParameters {
        quiet: true,
        time_limit: Some(args.time_limit),
        ..Default::default()
    };
    let cabs_parameters = CabsParameters {
        initial_beam_width: args.initial_beam_width,
        max_beam_width: Some(args.max_beam_width),
        keep_all_layers: args.keep_all_layers,
    };
    let mut solver: Box<dyn Search<CostType = i32, Label = Label>> =
        match (args.search_mode.as_str(), args.workers) {
            ("primal", 1) => {
                rpid::solvers::create_blind_cabs(model.clone(), search_parameters, cabs_parameters)
            }
            ("primal", workers) => rpid::solvers::create_blind_parallel_cabs(
                model.clone(),
                search_parameters,
                cabs_parameters,
                workers,
            ),
            ("dual", 1) => {
                rpid::solvers::create_cabs(model.clone(), search_parameters, cabs_parameters)
            }
            ("dual", workers) => rpid::solvers::create_parallel_cabs(
                model.clone(),
                search_parameters,
                cabs_parameters,
                workers,
            ),
            _ => return Err("unsupported reservoir DP search mode".into()),
        };
    let mut improvements = Vec::new();
    let solution = loop {
        let (solution, terminated) = solver.search_next();
        if let Some(cost) = solution.cost
            && improvements.last().map(|value: &Improvement| value.served)
                != Some(cost / OBJECTIVE_SCALE)
        {
            improvements.push(Improvement {
                elapsed_seconds: solution.time,
                served: cost / OBJECTIVE_SCALE,
            });
        }
        if terminated {
            break solution;
        }
    };
    let plan = if solution.cost.is_some() {
        Some(model.replay(&solution.transitions)?.1)
    } else {
        None
    };
    let status = if solution.is_optimal {
        "optimal"
    } else if solution.is_infeasible {
        "infeasible"
    } else if solution.is_time_limit_reached {
        "time_limit"
    } else if solution.cost.is_some() {
        "beam_limit"
    } else {
        "no_solution"
    };
    let output = Output {
        schema: "reservoir_symbolic_dp_result_v1",
        engine: format!("rpid-0.4.0-{}-cabs", args.search_mode),
        search_mode: args.search_mode,
        source_fingerprint: domain.source_fingerprint,
        status: status.into(),
        served: solution.cost.map(|cost| cost / OBJECTIVE_SCALE),
        best_bound_served: solution.best_bound.map(|bound| bound / OBJECTIVE_SCALE),
        is_optimal: solution.is_optimal,
        is_infeasible: solution.is_infeasible,
        time_limit_reached: solution.is_time_limit_reached,
        expanded: solution.expanded,
        generated: solution.generated,
        elapsed_seconds: solution.time,
        improvements,
        labels: solution.transitions,
        plan,
    };
    let bytes = serde_json::to_vec_pretty(&output).map_err(|error| error.to_string())?;
    fs::write(&args.output, bytes).map_err(|error| format!("cannot write output: {error}"))?;
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(2);
    }
}
