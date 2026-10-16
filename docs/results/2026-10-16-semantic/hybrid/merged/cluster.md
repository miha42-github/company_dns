# What the pods did during each step

Alignment: **alignment unknown** (the watch has no idle stretch before or after the run): the clocks were trusted as they are.

| in flight | requests/s | pods' CPU, median (cores) | max | CPU throttled, max | memory, largest pod (MiB) | fewest ready | new restarts | OOM kills |
|---|---|---|---|---|---|---|---|---|
| 192 | 206 | 19.52 | 22.61 | 5.9% | 274.9 | 20 | 0 | 0 |
| 384 | 206 | 16.19 | 23.84 | 5.8% | 274.8 | 20 | 0 | 0 |
| 768 | 207 | 19.57 | 23.68 | 7.0% | 298.4 | 19 | 0 | 0 |
