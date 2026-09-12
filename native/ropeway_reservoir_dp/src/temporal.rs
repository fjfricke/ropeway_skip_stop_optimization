//! Exact integer Simple Temporal Network (STN).
//!
//! `upper(i, j)` represents `x_j - x_i <= c`. Variable zero is the fixed
//! origin. Every mutating operation closes the distance-bound matrix, so a
//! negative diagonal is an exact infeasibility certificate for the branch.

use std::hash::{Hash, Hasher};

pub const INF: i64 = i64::MAX / 4;

#[derive(Clone, Debug, Eq)]
pub struct TemporalNetwork {
    size: usize,
    upper: Vec<i64>,
}

impl PartialEq for TemporalNetwork {
    fn eq(&self, other: &Self) -> bool {
        self.size == other.size && self.upper == other.upper
    }
}

impl Hash for TemporalNetwork {
    fn hash<H: Hasher>(&self, state: &mut H) {
        self.size.hash(state);
        self.upper.hash(state);
    }
}

impl Default for TemporalNetwork {
    fn default() -> Self {
        Self::new()
    }
}

impl TemporalNetwork {
    pub fn new() -> Self {
        Self {
            size: 1,
            upper: vec![0],
        }
    }

    pub fn len(&self) -> usize {
        self.size
    }

    pub fn is_empty(&self) -> bool {
        false
    }

    fn index(&self, from: usize, to: usize) -> usize {
        assert!(from < self.size && to < self.size);
        from * self.size + to
    }

    pub fn upper_bound(&self, from: usize, to: usize) -> i64 {
        self.upper[self.index(from, to)]
    }

    pub fn add_timepoint(&mut self, lower: i64, upper: i64) -> Option<usize> {
        if lower > upper {
            return None;
        }
        let old = self.size;
        let new = old.checked_add(1)?;
        let mut matrix = vec![INF; new.checked_mul(new)?];
        for i in 0..old {
            for j in 0..old {
                matrix[i * new + j] = self.upper[i * old + j];
            }
        }
        for i in 0..new {
            matrix[i * new + i] = 0;
        }
        self.size = new;
        self.upper = matrix;
        let variable = old;
        self.add_constraint(0, variable, upper)?;
        self.add_constraint(variable, 0, lower.checked_neg()?)?;
        Some(variable)
    }

    pub fn add_constraint(&mut self, from: usize, to: usize, bound: i64) -> Option<()> {
        let index = self.index(from, to);
        if bound >= self.upper[index] {
            return Some(());
        }
        let n = self.size;
        let reverse = self.upper_bound(to, from);
        if reverse != INF && reverse.checked_add(bound)? < 0 {
            return None;
        }

        // The matrix is closed before the new edge (from -> to, bound) is
        // inserted.  Every newly shorter path uses that edge exactly once, so
        // one O(n²) rank-one update gives the complete new closure.
        let mut updated = self.upper.clone();
        for i in 0..n {
            let left = self.upper[i * n + from];
            if left == INF {
                continue;
            }
            let prefix = left.checked_add(bound)?;
            for j in 0..n {
                let right = self.upper[to * n + j];
                if right == INF {
                    continue;
                }
                let candidate = prefix.checked_add(right)?;
                let target = i * n + j;
                if candidate < updated[target] {
                    updated[target] = candidate;
                }
            }
        }
        self.upper = updated;
        Some(())
    }

    pub fn add_equality(&mut self, from: usize, to: usize, offset: i64) -> Option<()> {
        self.add_constraint(from, to, offset)?;
        self.add_constraint(to, from, offset.checked_neg()?)
    }

    /// Cubic reference closure retained for differential tests and diagnostics.
    pub fn close(&mut self) -> Option<()> {
        let n = self.size;
        for k in 0..n {
            for i in 0..n {
                let ik = self.upper[i * n + k];
                if ik == INF {
                    continue;
                }
                for j in 0..n {
                    let kj = self.upper[k * n + j];
                    if kj == INF {
                        continue;
                    }
                    let candidate = ik.checked_add(kj)?;
                    let index = i * n + j;
                    if candidate < self.upper[index] {
                        self.upper[index] = candidate;
                    }
                }
            }
        }
        if (0..n).any(|i| self.upper[i * n + i] < 0) {
            None
        } else {
            Some(())
        }
    }

    pub fn implies(&self, from: usize, to: usize, bound: i64) -> bool {
        self.upper_bound(from, to) <= bound
    }

    /// A canonical latest feasible schedule relative to timepoint zero.
    pub fn latest_schedule(&self) -> Option<Vec<i64>> {
        let values = (0..self.size)
            .map(|j| self.upper_bound(0, j))
            .collect::<Vec<_>>();
        if values.contains(&INF) {
            return None;
        }
        for i in 0..self.size {
            for j in 0..self.size {
                let bound = self.upper_bound(i, j);
                if bound != INF && values[j].checked_sub(values[i])? > bound {
                    return None;
                }
            }
        }
        Some(values)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn closes_and_extracts_integer_schedule() {
        let mut network = TemporalNetwork::new();
        let a = network.add_timepoint(10, 20).unwrap();
        let b = network.add_timepoint(0, 100).unwrap();
        network.add_constraint(a, b, 7).unwrap();
        network.add_constraint(b, a, -5).unwrap();
        let values = network.latest_schedule().unwrap();
        assert!((10..=20).contains(&values[a]));
        assert!((5..=7).contains(&(values[b] - values[a])));
    }

    #[test]
    fn rejects_negative_cycle() {
        let mut network = TemporalNetwork::new();
        let a = network.add_timepoint(0, 10).unwrap();
        let b = network.add_timepoint(0, 10).unwrap();
        network.add_constraint(a, b, 2).unwrap();
        assert!(network.add_constraint(b, a, -3).is_none());
    }

    #[test]
    fn equality_and_large_ticks_are_exact() {
        let mut network = TemporalNetwork::new();
        let a = network.add_timepoint(3_000_000_000, 3_000_000_000).unwrap();
        let b = network.add_timepoint(0, 9_000_000_000).unwrap();
        network.add_equality(a, b, 1_200_000_000).unwrap();
        let values = network.latest_schedule().unwrap();
        assert_eq!(values[b], 4_200_000_000);
    }

    #[test]
    fn detects_invalid_initial_bounds() {
        let mut network = TemporalNetwork::new();
        assert!(network.add_timepoint(2, 1).is_none());
    }

    #[test]
    fn incremental_updates_match_full_floyd_warshall_closure() {
        let mut incremental = TemporalNetwork::new();
        for _ in 0..8 {
            incremental.add_timepoint(-100, 100).unwrap();
        }
        let mut reference = incremental.clone();
        let values = (0..incremental.len())
            .map(|index| index as i64 * 7)
            .collect::<Vec<_>>();
        let mut seed = 17u64;
        for _ in 0..100 {
            seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1);
            let from = seed as usize % incremental.len();
            seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1);
            let to = seed as usize % incremental.len();
            let slack = (seed % 13) as i64;
            let bound = values[to] - values[from] + slack;

            incremental.add_constraint(from, to, bound).unwrap();
            let index = reference.index(from, to);
            reference.upper[index] = reference.upper[index].min(bound);
            reference.close().unwrap();
            assert_eq!(incremental, reference);
        }

        let before = incremental.clone();
        assert!(incremental.add_constraint(1, 2, -1000).is_none());
        assert_eq!(incremental, before);
    }
}
