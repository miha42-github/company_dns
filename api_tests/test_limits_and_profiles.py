"""L5: access, profiles, rate limits and the SQL endpoint's guards and caps.

This is the Python home of what `v4/scripts/sql-try.sh check` verifies by shell (that script stays as the developer's local
playground). It runs against a server these tests start themselves (server.py), with throwaway profiles and small limits,
because it deliberately hammers it. Never run against someone else's server.

Server limits during these tests: default 50 / max 200 rows, 5 s timeout, 128 MB, 2 concurrent queries.
Profiles (see server.py): tester (SQL on sic and edgar), sic-only, no-sql (no rate-limit grant), unlimited, capped (20/min),
sql-small (5 rows, 2 s, concurrency 1), sql-rpm (20 SQL requests per minute). All inherit "no rate limit" from the defaults.
"""
import unittest
from concurrent.futures import ThreadPoolExecutor

from server import GENERIC_UA, SELF_UA, SLOW_SQL, ManagedServer, fresh_ip

SERVER = None


def setUpModule():
    global SERVER
    SERVER = ManagedServer()
    SERVER.start()  # raises SkipTest when there is no binary


def tearDownModule():
    if SERVER:
        SERVER.stop()


def lookup(who=None, ip=None, ua=GENERIC_UA, headers=None):
    return SERVER.call(who, "GET", "/V4.0/na/sic/code/7372", ua=ua, ip=ip, headers=headers)


class Access(unittest.TestCase):
    def test_no_credential_is_401_with_a_challenge(self):
        r = SERVER.sql(None, "select 1")
        self.assertEqual(r.status, 401)
        self.assertTrue(r.headers["WWW-Authenticate"].startswith("Basic"))
        self.assertEqual(r.json["code"], 401)

    def test_wrong_token_and_unknown_profile_are_401(self):
        self.assertEqual(SERVER.sql("tester", "select 1", token="not-the-token").status, 401)
        self.assertEqual(SERVER.sql("nobody", "select 1", token="x").status, 401)

    def test_a_forged_origin_is_accepted_for_nothing(self):
        r = SERVER.sql(None, "select 1", headers={"Origin": "https://mediumroast.io", "Referer": "https://mediumroast.io/"})
        self.assertEqual(r.status, 401)

    def test_profiles_without_sql_or_the_dataset_get_403(self):
        self.assertEqual(SERVER.sql("no-sql", "select 1").status, 403)
        self.assertEqual(SERVER.sql("sic-only", "select 1", dataset="edgar").status, 403)

    def test_a_granted_profile_gets_through(self):
        r = SERVER.sql("sic-only", "select 1 as one")
        self.assertEqual((r.status, r.json["data"]["rows"][0]["one"]), (200, 1))

    def test_unknown_dataset_and_empty_sql_are_400(self):
        self.assertEqual(SERVER.sql("tester", "select 1", dataset="nope").status, 400)
        self.assertEqual(SERVER.sql("tester", "   ").status, 400)

    def test_failed_logins_are_throttled_but_the_right_credential_still_works(self):
        ip = fresh_ip()
        statuses = [SERVER.sql("tester", "select 1", token="wrong", ip=ip).status for _ in range(12)]
        self.assertEqual(statuses[0], 401)
        self.assertEqual(statuses[-1], 429)
        self.assertEqual(SERVER.sql("tester", "select 1", ip=ip).status, 200)


class SqlData(unittest.TestCase):
    def test_it_queries_real_data(self):
        r = SERVER.sql("tester", "select count(*) as n from sic_data")
        self.assertGreater(r.json["data"]["rows"][0]["n"], 0)
        self.assertGreater(SERVER.sql("tester", "select count(*) as n from edgar_catalog", dataset="edgar").json["data"]["rows"][0]["n"], 0)

    def test_every_loaded_system_is_a_table(self):
        r = SERVER.sql("tester", "select table_name from information_schema.tables where table_schema = 'public'")
        self.assertGreaterEqual(r.json["data"]["row_count"], 1)

    def test_the_response_says_it_is_experimental(self):
        codes = [l["code"] for l in SERVER.sql("tester", "select 1").json["data"]["limitations"]]
        self.assertIn("experimental", codes)

    def test_bad_sql_is_400_with_a_message(self):
        r = SERVER.sql("tester", "selec 1")
        self.assertEqual(r.status, 400)
        self.assertTrue(r.json["message"])

    def test_the_embedding_columns_are_hidden(self):
        star = SERVER.sql("tester", "select * from sic_data limit 1").json["data"]["rows"][0]
        self.assertFalse([k for k in star if k.startswith("vector_")])
        self.assertEqual(SERVER.sql("tester", "select vector_all_minilm_l6_v2 from sic_data limit 1").status, 400)
        n = SERVER.sql("tester", "select count(*) as n from information_schema.columns where column_name like 'vector%'")
        self.assertEqual(n.json["data"]["rows"][0]["n"], 0)

    def test_only_single_read_only_statements_run(self):
        for sql in ["insert into sic_data select * from sic_data limit 1", "create table x as select 1", "drop table sic_data",
                    "create external table e (a int) stored as csv location '/etc/passwd'", "copy sic_data to '/tmp/out.csv'",
                    "set datafusion.execution.batch_size = 1", "select 1; select 2", "select * from '/etc/passwd'"]:
            with self.subTest(sql=sql):
                self.assertEqual(SERVER.sql("tester", sql).status, 400)
        self.assertGreater(SERVER.sql("tester", "select count(*) as n from sic_data").json["data"]["rows"][0]["n"], 0, "the table is intact")


class SqlLimits(unittest.TestCase):
    ROWS = "select * from generate_series(1, 1000)"

    def test_default_row_cap_explicit_limit_and_ceiling(self):
        r = SERVER.sql("tester", self.ROWS)
        self.assertEqual((r.json["data"]["row_count"], r.json["data"]["truncated"]), (50, True))
        self.assertEqual(SERVER.sql("tester", self.ROWS, limit=7).json["data"]["row_count"], 7)
        r = SERVER.sql("tester", self.ROWS, limit=100000)
        self.assertEqual((r.json["data"]["row_count"], r.json["data"]["limit"]), (200, 200))

    def test_a_runaway_query_is_cancelled_at_the_timeout(self):
        r = SERVER.sql("tester", SLOW_SQL)
        self.assertEqual(r.status, 504)
        self.assertLess(r.seconds, 9)

    def test_a_memory_hog_is_refused_cleanly(self):
        r = SERVER.sql("tester", "select string_agg(cast(value as varchar), ',') as s from generate_series(1, 300000000)")
        self.assertEqual(r.status, 422)
        self.assertIn("memory", r.json["message"])

    def test_the_concurrency_cap_refuses_instead_of_queueing(self):
        with ThreadPoolExecutor(6) as ex:
            replies = list(ex.map(lambda _: SERVER.sql("tester", SLOW_SQL), range(6)))
        statuses = sorted(r.status for r in replies)
        self.assertIn(429, statuses)
        self.assertTrue(all(s in (429, 504) for s in statuses), statuses)
        self.assertTrue([r for r in replies if r.status == 429][0].headers["Retry-After"])
        self.assertEqual(SERVER.sql("tester", "select 1").status, 200, "the server is fine afterwards")


class PerProfileSqlLimits(unittest.TestCase):
    def test_a_profile_can_lower_the_row_cap(self):
        r = SERVER.sql("sql-small", self.rows(), limit=100)
        self.assertEqual((r.json["data"]["row_count"], r.json["data"]["limit"], r.json["data"]["truncated"]), (5, 5, True))

    @staticmethod
    def rows():
        return "select * from generate_series(1, 1000)"

    def test_a_profile_can_lower_the_timeout(self):
        r = SERVER.sql("sql-small", SLOW_SQL)
        self.assertEqual(r.status, 504)
        self.assertLess(r.seconds, 4.5, "its 2 s, not the server's 5 s")

    def test_a_profile_has_its_own_concurrency_gate(self):
        with ThreadPoolExecutor(3) as ex:
            statuses = sorted(r.status for r in ex.map(lambda _: SERVER.sql("sql-small", SLOW_SQL), range(3)))
        self.assertIn(429, statuses, statuses)

    def test_a_profile_has_its_own_request_rate(self):
        statuses = [SERVER.sql("sql-rpm", "select 1").status for _ in range(12)]
        self.assertIn(429, statuses)
        self.assertTrue(all(s in (200, 429) for s in statuses), statuses)


class SqlGoesThroughTheLimiter(unittest.TestCase):
    def test_anonymous_with_a_forged_origin_is_limited_like_anyone(self):
        ip = fresh_ip()
        forged = {"Origin": "https://mediumroast.io"}
        statuses = [SERVER.sql(None, "select 1", ip=ip, ua=GENERIC_UA, headers=forged).status for _ in range(3)]
        self.assertEqual(statuses[0], 401)
        self.assertIn(429, statuses[1:])

    def test_a_wrong_credential_is_a_401_never_anonymous(self):
        self.assertEqual(SERVER.sql("tester", "select 1", token="wrong", ua=GENERIC_UA).status, 401)


class LookupRateLimits(unittest.TestCase):
    """The User-Agent ladder and profile grants on the lookup routes."""

    def test_anonymous_with_a_generic_user_agent_gets_the_draconian_tier(self):
        ip = fresh_ip()
        first, second = lookup(ip=ip), lookup(ip=ip)
        self.assertEqual((first.status, second.status), (200, 429))
        self.assertTrue(second.headers["Retry-After"])

    def test_a_self_identifying_user_agent_gets_the_normal_tier(self):
        ip = fresh_ip()
        self.assertEqual([lookup(ip=ip, ua=SELF_UA).status for _ in range(5)], [200] * 5)

    def test_the_tiers_are_separate_buckets(self):
        ip = fresh_ip()
        lookup(ip=ip)
        self.assertEqual(lookup(ip=ip).status, 429)
        self.assertEqual(lookup(ip=ip, ua=SELF_UA).status, 200)

    def test_a_profile_without_a_rate_limit_grant_gets_the_normal_tier_whatever_its_user_agent(self):
        ip = fresh_ip()
        self.assertEqual([lookup("no-sql", ip=ip).status for _ in range(4)], [200] * 4)

    def test_a_bypass_profile_is_not_limited(self):
        ip = fresh_ip()
        self.assertEqual({lookup("unlimited", ip=ip).status for _ in range(25)}, {200})

    def test_a_quota_profile_has_its_own_bucket(self):
        statuses = [lookup("capped").status for _ in range(12)]
        self.assertIn(429, statuses)
        self.assertTrue(all(s in (200, 429) for s in statuses), statuses)

    def test_a_wrong_credential_on_a_lookup_is_401_not_anonymous(self):
        self.assertEqual(SERVER.call("capped", "GET", "/V4.0/na/sic/code/7372", token="wrong", ip=fresh_ip()).status, 401)

    def test_health_is_never_rate_limited(self):
        ip = fresh_ip()
        self.assertEqual({SERVER.call(None, "GET", "/health", ua=GENERIC_UA, ip=ip).status for _ in range(10)}, {200})


class ErrorsOnTheManagedServer(unittest.TestCase):
    def test_a_wrong_credential_is_a_json_401_on_every_kind_of_route(self):
        for path in ("/V4.0/na/sic/code/7372", "/V3.0/eu/sic/section/A", "/V2.0/sic/code/3571", "/V4.0/global/sic/description/software"):
            with self.subTest(path=path):
                r = SERVER.call("tester", "GET", path, token="wrong", ip=fresh_ip())
                self.assertEqual((r.status, r.json["code"]), (401, 401))


if __name__ == "__main__":
    unittest.main()
