from datetime import datetime

from ropeway_skip_stop_optimization.models import Scenario


def service_duration_seconds(scenario: Scenario) -> float:
    start = datetime.combine(datetime.min.date(), scenario.service_start_time)
    end = datetime.combine(datetime.min.date(), scenario.service_end_time)
    return (end - start).total_seconds()
