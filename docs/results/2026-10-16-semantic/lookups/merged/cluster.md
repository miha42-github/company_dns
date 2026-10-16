# What the pods did during each step

Alignment: **alignment unknown** (the watch has no idle stretch before or after the run): the clocks were trusted as they are.

| in flight | requests/s | pods' CPU, median (cores) | max | CPU throttled, max | memory, largest pod (MiB) | fewest ready | new restarts | OOM kills |
|---|---|---|---|---|---|---|---|---|
| 256 | 1843 | 17.81 | 21.15 | 4.5% | 280.2 | 20 | 0 | 0 |
| 512 | 2002 | 18.48 | 20.12 | 4.0% | 280.0 | 20 | 0 | 0 |
| 768 | 2027 | 18.15 | 20.47 | 3.9% | 280.2 | 20 | 0 | 0 |
| 1024 | 2052 | 18.93 | 22.45 | 8.0% | 280.2 | 20 | 0 | 0 |
| 1536 | 2153 | 19.56 | 22.83 | 7.7% | 280.6 | 20 | 0 | 0 |
| 2048 | 2132 | 19.5 | 23.43 | 5.7% | 281.8 | 20 | 0 | 0 |
| 3072 | 2074 | 19.0 | 23.34 | 5.5% | 281.2 | 19 | 1 | 0 |
