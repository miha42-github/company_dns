# What the pods did during each step

Alignment: **alignment unknown** (the watch has no idle stretch before or after the run): the clocks were trusted as they are.

| in flight | requests/s | pods' CPU, median (cores) | max | CPU throttled, max | memory, largest pod (MiB) | fewest ready | new restarts | OOM kills |
|---|---|---|---|---|---|---|---|---|
| 192 | 801 | 19.94 | 23.4 | 4.6% | 275.2 | 20 | 0 | 0 |
| 384 | 807 | 19.59 | 23.53 | 6.2% | 275.1 | 20 | 0 | 0 |
| 768 | 815 | 20.02 | 22.13 | 5.0% | 275.1 | 20 | 0 | 0 |
