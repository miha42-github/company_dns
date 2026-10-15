"""Tests for scripts/check_hygiene.py. Run: python3 scripts/test_check_hygiene.py

Strings that would be findings are built at run time, so this file itself stays clean.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_hygiene as ch  # noqa: E402

SCRIPT = Path(__file__).resolve().parent / "check_hygiene.py"


def scan(text, denylist=()):
    return [f[2] for f in ch.scan_text("f", text, list(denylist))]


class Hygiene(unittest.TestCase):
    def test_addresses_in_the_documentation_ranges_loopback_and_public_resolvers_pass(self):
        for ok in ("192.0.2.10", "198.51.100.7", "203.0.113.200", "127.0.0.1", "0.0.0.0", "1.1.1.1"):
            self.assertEqual(scan(f"at {ok} now"), [], ok)

    def test_private_and_public_addresses_are_findings(self):
        a, b, c = ".".join(("192", "168", "1", "20")), ".".join(("10", "4", "5", "6")), ".".join(("52", "1", "2", "3"))
        self.assertIn(f"a private address ({a})", scan(f"host {a}"))
        self.assertIn(f"a private address ({b})", scan(f"host {b}:8080"))
        self.assertIn(f"an IP address ({c})", scan(f"host {c}"))

    def test_version_numbers_and_longer_dotted_numbers_are_not_addresses(self):
        for ok in ("version 1.2.3.999", "v4.0.0.1-rc", "1.2.3.4.5", "x1.2.3.4"):
            self.assertEqual(scan(ok), [], ok)

    def test_internal_host_names_emails_secrets_and_home_paths(self):
        self.assertTrue(scan("ssh box." + "lan"))
        self.assertTrue(scan("db." + "internal:5432"))
        self.assertTrue(scan("write to someone" + "@corp.test"))
        self.assertEqual(scan("write to hello@mediumroast.io or you@example.org or a@b.example or git@github.com"), [])
        self.assertTrue(scan("token " + "ghp_" + "a" * 36))
        self.assertTrue(scan("-----BEGIN " + "PRIVATE KEY-----"))
        self.assertTrue(scan("cd /" + "Users/" + "someone/dev"))
        self.assertEqual(scan("cd /home/user/dev or /Users/you/dev"), [])

    def test_an_allow_comment_skips_the_line(self):
        self.assertEqual(scan("x " + ".".join(("10", "0", "0", "10")) + "  # hygiene: allow"), [])

    def test_the_private_denylist_matches_whole_words_only(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write("# lab names\nsecretnode-1\n")
        self.addCleanup(os.unlink, f.name)
        deny = ch.load_denylist(f.name)
        self.assertTrue(scan("run on SecretNode-1 today", deny))
        self.assertEqual(scan("run on secretnode-12", deny), [])

    def test_wildcards_and_regular_expressions_in_the_deny_list(self):
        net = ".".join(("10", "9", "8")) + "."  # built at run time so this file stays clean
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(f"# patterns\n{net}*\n*.corp.example\nre:svc(42)?user\nsecretbox\n")
        self.addCleanup(os.unlink, f.name)
        deny = ch.load_denylist(f.name)
        self.assertTrue(any("deny-list" in w for w in scan(f"at {net}77 now", deny)), "any address in the network")
        self.assertTrue(scan("host db1.corp.example is up", deny), "any host name under the domain")
        self.assertTrue(scan("user svc42user and svcuser", deny), "a regular expression")
        self.assertTrue(scan("run on SecretBox today", deny), "a literal term still works")
        neighbours = ".".join(("10", "9", "80", "1")) + " corp.example.org.uk"
        self.assertFalse(any("deny-list" in w for w in scan(neighbours, deny)), "no false matches on neighbours")

    def test_the_command_exits_1_on_a_finding_and_0_when_clean(self):
        with tempfile.TemporaryDirectory() as d:
            bad, good = Path(d) / "bad.txt", Path(d) / "good.txt"
            bad.write_text("host " + ".".join(("172", "16", "0", "5")) + "\n")
            good.write_text("host 192.0.2.5\n")
            r = subprocess.run([sys.executable, str(SCRIPT), str(bad)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn("bad.txt:1", r.stdout)
            self.assertEqual(subprocess.run([sys.executable, str(SCRIPT), str(good)], capture_output=True, text=True).returncode, 0)
            self.assertEqual(subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True,
                                            env={**os.environ, "HYGIENE_DENYLIST": "/nonexistent"}).returncode, 2)

    def test_commit_messages_on_every_branch_are_checked(self):
        with tempfile.TemporaryDirectory() as d:
            def git(*a):
                subprocess.run(["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@example.org", *a], check=True, capture_output=True)
            git("init", "-q", "-b", "main")
            (Path(d) / "f").write_text("x\n")
            git("add", "f")
            git("commit", "-q", "-m", "fine")
            git("checkout", "-q", "-b", "side")
            git("commit", "-q", "--allow-empty", "-m", "moved the service to " + ".".join(("192", "168", "7", "7")))
            git("checkout", "-q", "main")
            saved = ch.REPO_ROOT
            ch.REPO_ROOT = Path(d)
            try:
                found = ch.scan_messages([])
            finally:
                ch.REPO_ROOT = saved
            self.assertEqual(len(found), 1, found)
            self.assertIn("private address", found[0][2])

    def test_the_repository_itself_is_clean(self):
        self.assertEqual(ch.scan_files(ch.tracked_files(), []), [])


if __name__ == "__main__":
    unittest.main()
