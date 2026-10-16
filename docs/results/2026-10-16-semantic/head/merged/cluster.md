# What the pods did during each step

Alignment: **alignment unknown** (the watch has no idle stretch before or after the run): the clocks were trusted as they are.

| in flight | requests/s | pods' CPU, median (cores) | max | CPU throttled, max | memory, largest pod (MiB) | fewest ready | new restarts | OOM kills |
|---|---|---|---|---|---|---|---|---|
| 48 | 310 | 17.82 | 21.02 | 4.8% | 187.3 | 20 | 0 | 0 |
| 96 | 324 | 18.64 | 22.44 | 4.3% | 205.1 | 20 | 0 | 0 |
| 192 | 328 | 19.25 | 19.76 | 6.1% | 226.4 | 20 | 0 | 0 |
| 384 | 338 | 19.25 | 22.82 | 8.2% | 237.6 | 20 | 0 | 0 |
| 768 | 330 | 18.11 | 23.59 | 7.1% | 286.9 | 20 | 0 | 0 |
