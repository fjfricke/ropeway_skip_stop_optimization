from __future__ import annotations

import argparse
import json
from pathlib import Path

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_cp_sat import DddFixedKCpSatRunConfig, run_ddd_fixed_k_cp_sat
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import DddIntegratedCpSatConfig
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_passenger import DddCpSatCostEncoding
from ropeway_skip_stop_optimization.optimization.ddd.fixed_k import DddFixedKStartPolicy, DddFixedKOperatingMode


def main() -> None:
    parser=argparse.ArgumentParser(description='Integrated exact Fixed-K No-Wait CP-SAT with integer passengers.')
    parser.add_argument('--example',required=True)
    parser.add_argument('--cabins','--cabin-count',dest='cabins',type=int,required=True)
    parser.add_argument('--mode',choices=[v.value for v in DddFixedKOperatingMode],default='skip_stop')
    parser.add_argument('--start-policy',choices=['canonical_rope','balanced_reference'],default='balanced_reference')
    parser.add_argument('--objective',choices=['journey_time'],default='journey_time')
    parser.add_argument('--time-limit','--time-limit-seconds',dest='time_limit',type=float,default=60)
    parser.add_argument('--num-workers',type=int,default=1)
    parser.add_argument('--seed',type=int,default=0)
    parser.add_argument('--cost-encoding',choices=[v.value for v in DddCpSatCostEncoding],default='product')
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--checkpoint',type=Path)
    parser.add_argument('--start-layout-time-limit',type=float,default=120)
    parser.add_argument('--seed-passenger-time-limit',type=float,default=30)
    parser.add_argument('--build-only',action='store_true')
    parser.add_argument('--log-search-progress',action='store_true')
    sources=parser.add_mutually_exclusive_group()
    sources.add_argument('--primal-seed-result',type=Path)
    sources.add_argument('--primal-seed-checkpoint',type=Path,help='Existing Root-CG checkpoint')
    sources.add_argument('--resume-checkpoint',type=Path,help='Validated native CP-SAT checkpoint (warm start)')
    sources.add_argument('--fixed-movement-result',type=Path,help='Arc-Flow result or native CP checkpoint; diagnostic proof scope')
    args=parser.parse_args()
    config=DddFixedKCpSatRunConfig(example_id=args.example,cabin_count=args.cabins,output_dir=args.output_dir,
        solver=DddIntegratedCpSatConfig(total_time_limit_seconds=args.time_limit,num_workers=args.num_workers,
            seed=args.seed,cost_encoding=DddCpSatCostEncoding(args.cost_encoding),checkpoint_path=args.checkpoint,
            log_search_progress=args.log_search_progress),
        start_policy=DddFixedKStartPolicy(args.start_policy),operating_mode=DddFixedKOperatingMode(args.mode),
        start_layout_time_limit_seconds=args.start_layout_time_limit,
        seed_passenger_time_limit_seconds=args.seed_passenger_time_limit,
        primal_seed_result=args.primal_seed_result,primal_seed_checkpoint=args.primal_seed_checkpoint,
        resume_checkpoint=args.resume_checkpoint,fixed_movement_result=args.fixed_movement_result,build_only=args.build_only)
    result=run_ddd_fixed_k_cp_sat(config)
    fields=('solver_status','termination_reason','proof_scope','validated_upper_bound','cp_lower_bound','relative_gap','total_wall_seconds','model_stats')
    print(json.dumps({key:result.get(key) for key in fields},indent=2))


if __name__=='__main__':
    main()
