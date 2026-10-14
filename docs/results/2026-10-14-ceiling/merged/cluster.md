# What the pods did during each step

Alignment: the run's times were shifted by -4 s onto the watcher's clock, found from the pods' CPU rising and falling.

| in flight | requests/s | pods' CPU, median (cores) | max | CPU throttled, max | memory, largest pod (MiB) | fewest ready | new restarts | OOM kills |
|---|---|---|---|---|---|---|---|---|
| 256 | 1756 | 17.45 | 18.89 | 3.3% | 165.9 | 20 | 0 | 0 |
| 512 | 1931 | 18.09 | 20.4 | 5.6% | 166.7 | 20 | 0 | 0 |
| 768 | 2066 | 19.29 | 20.32 | 6.0% | 166.9 | 20 | 0 | 0 |
| 1024 | 2061 | 19.19 | 21.03 | 7.7% | 166.9 | 20 | 0 | 0 |
| 1536 | 2144 | 18.08 | 21.65 | 6.1% | 168.2 | 20 | 0 | 0 |
| 2048 | 2145 | 18.29 | 21.4 | 5.9% | 170.4 | 20 | 0 | 0 |
| 3072 | 2080 | 19.31 | 21.19 | 6.3% | 172.1 | 18 | 0 | 0 |
