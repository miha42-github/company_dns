# What the pods did during each step

Alignment: **alignment unknown** (the watch has no idle stretch before or after the run): the clocks were trusted as they are.

| in flight | requests/s | pods' CPU, median (cores) | max | CPU throttled, max | memory, largest pod (MiB) | fewest ready | new restarts | OOM kills |
|---|---|---|---|---|---|---|---|---|
| 192 | 284 | 19.73 | 23.18 | 6.9% | 274.7 | 20 | 0 | 0 |
| 384 | 284 | 19.78 | 22.96 | 5.8% | 274.9 | 20 | 0 | 0 |
| 768 | 286 | 19.78 | 21.31 | 6.9% | 275.1 | 20 | 0 | 0 |
