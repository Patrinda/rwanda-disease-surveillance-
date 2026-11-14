"""Synthetic outbreak history used to help train the model.

The real (fictional) database holds one year in which only a few outbreaks happen. A model
trained on that alone learns that high weeks usually fall back, because most spikes are
just random noise. To teach it what a real outbreak looks like, we add two years of
generated history for the same districts and diseases:

    * a quiet background taken from each series' own average level,
    * week to week randomness (counts that vary more than a plain Poisson draw),
    * occasional outbreak episodes that rise, stay high for a while and fall again,
    * some false alarms that rise for a few days and fall straight away.

The generated days are only used for training. The check of the model always uses real weeks.
"""
from datetime import timedelta

import numpy as np

from .ml import Dataset

EPISODES_PER_SERIES_YEAR = 0.08
FALSE_ALARM_SHARE = 0.3


def _episode_profile(rng, days):
    """Extra weekly cases over time for one episode, as a list of daily multipliers of the peak."""
    false_alarm = rng.rand() < FALSE_ALARM_SHARE
    rise = rng.randint(4, 9) if false_alarm else rng.randint(10, 36)
    hold = rng.randint(0, 3) if false_alarm else rng.randint(7, 29)
    fall = rng.randint(5, 12) if false_alarm else rng.randint(14, 41)
    up = np.linspace(0.05, 1.0, rise) ** 1.6
    down = np.linspace(1.0, 0.0, fall)
    return np.concatenate([up, np.ones(hold), down])


def make_synthetic(real, years=2, seed=7):
    """Return a Dataset of generated history shaped like the real one."""
    rng = np.random.RandomState(seed)
    days = 365 * years
    start = real.start - timedelta(days=days + 30)
    syn = Dataset(start, start + timedelta(days=days - 1), real.districts, real.diseases)
    quiet_days = max(int(real.days * 0.75), 30)                     # leave out the newest weeks, where outbreaks are
    base_daily = real.counts[:, :quiet_days].mean(axis=1)
    for s in range(real.counts.shape[0]):
        rate = np.full(days, base_daily[s])
        weekly_noise = rng.gamma(shape=6.0, scale=1 / 6.0, size=days // 7 + 1)
        rate = rate * np.repeat(weekly_noise, 7)[:days]
        for _ in range(rng.poisson(EPISODES_PER_SERIES_YEAR * years)):
            profile = _episode_profile(rng, days)
            first = rng.randint(30, days - len(profile) - 10)
            peak_weekly = rng.uniform(3, 25)
            rate[first : first + len(profile)] += peak_weekly / 7.0 * profile
        syn.counts[s] = rng.poisson(rate)
    return syn
