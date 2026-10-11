"""Tests for the staging scripts, run against stub `kubectl`, `docker` and `curl` programs, so nothing touches a cluster, a registry or the network.
Run: python3 -m unittest k8s/test_staging_scripts.py

* v4/scripts/build-and-push.sh (WP2): refuses a dirty tree and a `latest` tag, names the tag from the date and commit, builds the V4 package for
  amd64, pushes only when asked, checks the image pulls with no credentials, and records what it pushed.
* k8s/staging/deploy.sh (WP5): can only touch company-dns-staging, refuses `latest`, puts the tag in as it applies (the repository file is not edited),
  applies in the safe order, stops if the credentials Secret is missing, and rolls back.
See docs/plans/v4-staging-rollout.md.
"""
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

KUBECTL = r'''#!/usr/bin/env bash
echo "kubectl $*" >> "$STUB_LOG"
case "$*" in
  *"apply"*"-f -"*) echo "(stdin captured)" >> "$STUB_LOG"; cat > "$STUB_LOG.stdin";;
esac
case "$*" in
  "config current-context") echo stub-context;;
  *"get secret"*) [ "${STUB_SECRET:-present}" = missing ] && exit 1; echo secret;;
  *"jsonpath={.spec.replicas}"*) echo 2;;
  *"jsonpath={.status.readyReplicas}"*) echo "${STUB_READY:-2}";;
  *"jsonpath={.spec.template.spec.containers[0].image}"*) echo "stub-image";;
esac
exit 0
'''
CURL = r'''#!/usr/bin/env bash
echo "curl $*" >> "$STUB_LOG"
case "$*" in *api.github.com/user*) echo '{"login": "tester"}';; *) echo '{}';; esac
exit 0
'''
DOCKER = r'''#!/usr/bin/env bash
echo "docker $* [DOCKER_CONFIG=${DOCKER_CONFIG:-}]" >> "$STUB_LOG"
case "$1" in
  login) cat >/dev/null;;
  pull) [ "${STUB_PULL:-ok}" = fail ] && exit 1;;
  inspect) echo "ghcr.io/miha42-github/company_dns/company_dns_v4@sha256:abc123";;
esac
exit 0
'''
SCRIPT_STUB = '#!/usr/bin/env bash\necho "$(basename "$0") $*" >> "$STUB_LOG"\n'


def write_exe(path: Path, text: str) -> None:
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.log = self.tmp / "stub.log"
        self.log.write_text("")
        for name, body in (("kubectl", KUBECTL), ("curl", CURL), ("docker", DOCKER)):
            write_exe(self.bin / name, body)
        self.env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "STUB_LOG": str(self.log)}

    def calls(self) -> str:
        return self.log.read_text()


class BuildAndPush(Base):
    def setUp(self):
        super().setUp()
        self.repo = self.tmp / "repo"
        scripts = self.repo / "v4" / "scripts"
        scripts.mkdir(parents=True)
        shutil.copy(REPO / "v4/scripts/build-and-push.sh", scripts / "build-and-push.sh")
        write_exe(scripts / "docker-build.sh", SCRIPT_STUB)
        write_exe(scripts / "docker-smoke.sh", SCRIPT_STUB)
        (self.repo / "v4" / "data-manifest.json").write_text('{"files": {}}\n')
        (self.repo / ".env").write_text("GITHUB_PAT=ghp_test\n")
        (self.repo / ".gitignore").write_text(".env\nv4/.build-log\n")
        git = lambda *a: subprocess.run(["git", *a], cwd=self.repo, check=True, capture_output=True, env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
        git("init", "-q")
        git("add", "-A")
        git("commit", "-q", "-m", "x")
        self.git = git

    def run_script(self, *args, **env):
        return subprocess.run([str(self.repo / "v4/scripts/build-and-push.sh"), *args], cwd=self.repo, env={**self.env, **env}, capture_output=True, text=True)

    def record(self):
        return json.loads((self.repo / "v4/.build-log").read_text().strip().splitlines()[-1])

    def test_the_default_tag_is_the_date_and_the_commit_and_the_image_is_the_v4_package_for_amd64(self):
        r = self.run_script("--no-push")
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = self.record()
        self.assertRegex(rec["tag"], r"^\d{8}-[0-9a-f]{7}$")
        self.assertEqual(rec["image"], f"ghcr.io/miha42-github/company_dns/company_dns_v4:{rec['tag']}")
        self.assertEqual((rec["profile"], rec["platform"], rec["dirty"], rec["pushed"]), ("release-small", "linux/amd64", False, False))
        build = [l for l in self.calls().splitlines() if l.startswith("docker-build.sh")][0]
        self.assertIn(f"-t {rec['image']}", build)
        self.assertIn("-p release-small", build)
        self.assertIn("--platform linux/amd64", build)

    def test_no_push_neither_logs_in_nor_pushes(self):
        self.run_script("--no-push")
        self.assertNotIn("docker login", self.calls())
        self.assertNotIn("docker push", self.calls())

    def test_a_dirty_tree_is_refused_unless_allowed_and_then_the_tag_says_so(self):
        (self.repo / "v4/data-manifest.json").write_text('{"files": {"x": 1}}\n')
        r = self.run_script("--no-push")
        self.assertEqual(r.returncode, 1)
        self.assertIn("uncommitted", r.stderr)
        r = self.run_script("--no-push", "--allow-dirty")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.record()["tag"].endswith("-dirty"))
        self.assertTrue(self.record()["dirty"])

    def test_latest_and_odd_tags_and_unknown_profiles_are_refused(self):
        for args in (["--tag", "latest"], ["--tag", "a b"], ["-p", "release-fat"]):
            r = self.run_script("--no-push", *args)
            self.assertEqual(r.returncode, 2, args)
        self.assertNotIn("docker-build.sh", self.calls())

    def test_smoke_runs_by_default_and_only_the_flag_skips_it(self):
        self.run_script("--no-push")
        self.assertIn("docker-smoke.sh", self.calls())
        self.log.write_text("")
        self.run_script("--no-push", "--skip-smoke")
        self.assertNotIn("docker-smoke.sh", self.calls())

    def test_a_failed_build_stops_before_anything_is_pushed(self):
        write_exe(self.repo / "v4/scripts/docker-build.sh", "#!/usr/bin/env bash\nexit 1\n")
        r = self.run_script()
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("docker push", self.calls())

    def test_push_logs_in_pushes_checks_an_anonymous_pull_and_records_the_digest(self):
        r = self.run_script("--tag", "10112026-abc1234")
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.calls().splitlines()
        i_login = next(i for i, l in enumerate(calls) if l.startswith("docker login"))
        i_push = next(i for i, l in enumerate(calls) if l.startswith("docker push"))
        i_pull = next(i for i, l in enumerate(calls) if l.startswith("docker pull"))
        self.assertLess(i_login, i_push)
        self.assertLess(i_push, i_pull)
        self.assertIn("-u tester", calls[i_login])
        self.assertNotIn("DOCKER_CONFIG=]", calls[i_pull], "the verification pull must use an empty Docker config, not the logged-in one")
        rec = self.record()
        self.assertEqual((rec["tag"], rec["pushed"]), ("10112026-abc1234", True))
        self.assertTrue(rec["digest"].endswith("sha256:abc123"))
        self.assertRegex(rec["data_manifest_sha256"], r"^[0-9a-f]{64}$")

    def test_a_private_package_fails_the_anonymous_pull_with_instructions(self):
        r = self.run_script("--tag", "10112026-abc1234", STUB_PULL="fail")
        self.assertEqual(r.returncode, 1)
        self.assertIn("public", r.stderr)

    def test_pushing_without_a_token_file_stops_before_login(self):
        (self.repo / ".env").unlink()
        r = self.run_script("--tag", "10112026-abc1234")
        self.assertEqual(r.returncode, 1)
        self.assertIn("GITHUB_PAT", r.stderr)
        self.assertNotIn("docker push", self.calls())


class Deploy(Base):
    SCRIPT = REPO / "k8s/staging/deploy.sh"

    def run_script(self, *args, **env):
        return subprocess.run([str(self.SCRIPT), *args], env={**self.env, **env}, capture_output=True, text=True, cwd=self.tmp)

    def kubectl_calls(self):
        return [l for l in self.calls().splitlines() if l.startswith("kubectl ")]

    def test_a_tag_is_required_and_latest_is_refused(self):
        self.assertEqual(self.run_script().returncode, 2)
        self.assertEqual(self.run_script("latest").returncode, 2)
        self.assertEqual(self.run_script("a;b").returncode, 2)
        self.assertEqual(self.run_script("--rollback", "latest").returncode, 2)
        self.assertEqual(self.kubectl_calls(), [])

    def test_it_only_touches_the_staging_namespace(self):
        r = self.run_script("10112026-abc1234")
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.kubectl_calls()
        namespaces = {m for l in calls for m in re.findall(r"-n (\S+)", l)}
        self.assertEqual(namespaces, {"company-dns-staging"})
        for l in calls:
            self.assertNotIn("delete", l)
            self.assertNotIn("--all-namespaces", l)
            self.assertNotIn(" -A", l)

    def test_the_tag_goes_into_the_applied_deployment_and_the_repository_file_is_not_edited(self):
        before = (REPO / "k8s/staging/deployment.yaml").read_text()
        self.run_script("10112026-abc1234")
        applied = Path(str(self.log) + ".stdin").read_text()
        image_lines = [l.strip() for l in applied.splitlines() if l.strip().startswith("image:")]
        self.assertEqual(image_lines, ["image: ghcr.io/miha42-github/company_dns/company_dns_v4:10112026-abc1234"])
        self.assertEqual((REPO / "k8s/staging/deployment.yaml").read_text(), before)
        self.assertIn("UNSET", before)

    def test_the_order_is_namespace_config_workload_smoke_then_ingress(self):
        self.run_script("--first-time", "10112026-abc1234")
        calls = self.calls().splitlines()
        def at(needle, start=0):
            return next(i for i, l in enumerate(calls) if i >= start and needle in l)
        i_ns = at("namespace.yaml")
        i_rules = at("configmap-rules.yaml")
        i_dep = at("apply -f -")  # the Deployment, from stdin with the tag in place
        i_rollout = at("rollout status")
        i_health = at("/health")
        i_ing = at("ingress.yaml")
        i_cert = at("certificate.yaml")
        self.assertTrue(i_ns < i_rules < i_dep < i_rollout < i_health < i_ing < i_cert, [i_ns, i_rules, i_dep, i_rollout, i_health, i_ing, i_cert])

    def test_a_missing_credentials_secret_stops_before_the_workload(self):
        r = self.run_script("10112026-abc1234", STUB_SECRET="missing")
        self.assertEqual(r.returncode, 1)
        self.assertIn("company-dns-credentials", r.stderr)
        applied = "\n".join(self.kubectl_calls())
        self.assertNotIn("apply -f -", applied)
        self.assertNotIn("ingress.yaml", applied)

    def test_a_dry_run_changes_nothing(self):
        r = self.run_script("--dry-run", "10112026-abc1234")
        self.assertEqual(r.returncode, 0, r.stderr)
        applies = [l for l in self.kubectl_calls() if " apply " in l]
        self.assertGreaterEqual(len(applies), 8)
        for l in applies:
            self.assertIn("--dry-run=server", l)
        self.assertNotIn("rollout", self.calls())

    def test_not_every_replica_ready_is_a_failure(self):
        r = self.run_script("10112026-abc1234", STUB_READY="1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not every replica is ready", r.stderr)

    def test_rollback_without_a_tag_undoes_the_rollout(self):
        r = self.run_script("--rollback")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(any("rollout undo deployment/company-dns" in l for l in self.kubectl_calls()))
        self.assertNotIn("apply", "\n".join(self.kubectl_calls()))

    def test_rollback_with_a_tag_deploys_that_tag(self):
        r = self.run_script("--rollback", "10102026-abc1234")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("company_dns_v4:10102026-abc1234", Path(str(self.log) + ".stdin").read_text())
        self.assertNotIn("rollout undo", self.calls())


if __name__ == "__main__":
    unittest.main()
