# Soak events: PASS

`studio-lan`: 6 events, each judged over the next 5 minutes. The quiet baseline p95 is 93 ms; an event passes with no errors, every canary right and p95 within 1.5x of it.

Alignment: the soak's times were shifted by -2 s onto the watcher's clock, found from the pods' CPU rising when the soak started and falling when it ended (start -2 s, end -4 s; resolution about 5 s).

| time (UTC) | what | verdict | windows | errors | wrong canaries | worst p95 ms | fewest ready | most terminating | restarts | peak memory MiB | |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-14T01:58:11Z | soak started | **PASS** | 6 | 0 | 0 | 94 | 20 | 0 | 0 | 191.5 |  |
| 2026-10-14T02:09:01Z | delete one pod | **PASS** | 6 | 0 | 0 | 95 | 20 | 1 | 0 | 191.6 |  |
| 2026-10-14T02:19:49Z | delete two pods | **PASS** | 6 | 0 | 0 | 98 | 18 | 2 | 0 | 191.6 |  |
| 2026-10-14T02:31:21Z | restart all pods | **PASS** | 6 | 0 | 0 | 92 | 20 | 8 | 0 | 191.4 |  |
| 2026-10-14T02:38:11Z | scale down to 16 | **PASS** | 6 | 0 | 0 | 96 | 16 | 4 | 0 | 164.7 |  |
| 2026-10-14T02:48:30Z | scale up to 20 | **PASS** | 6 | 0 | 0 | 96 | 16 | 0 | 0 | 164.9 |  |
