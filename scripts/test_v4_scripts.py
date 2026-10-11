"""Tests for scripts/build-and-deploy-v4.sh and scripts/seal-secrets-v4.sh, run against stub `kubectl`, `docker`, `curl`, `kubeseal` and the build
scripts, so nothing touches a cluster, a registry or the network. Run: python3 scripts/test_v4_scripts.py

The properties pinned here are the ones a staging deploy must not lose: only the staging namespace is touched and nothing is deleted; the tag is pinned
(never latest) and goes into the Deployment as it is applied while the repository is left alone; the order (credentials, config, workload, rollout, smoke
test, then Ingress); a failed rollout is rolled back; the preflight lists every problem at once; secrets never leave a private directory outside the
repository and tokens are never printed or put on a command line. See docs/plans/v4-staging-scripts.md and docs/v4-bringup.md.
"""
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEPLOY_SH = "build-and-deploy-v4.sh"
SEAL_SH = "seal-secrets-v4.sh"

KUBECTL = r'''#!/usr/bin/env bash
S="$STUB_STATE"
echo "kubectl $*" >> "$S/calls.log"
args="$*"
case "$args" in *"apply"*"-f -"*) cat > "$S/deploy.stdin";; esac
if [[ "$args" == "apply "* || "$args" == *" apply "* ]]; then
  # what real kubectl prints: "<kind>/<name> configured" when it changed something, "unchanged" otherwise
  if [[ "$args" == *configmap-rules.yaml* ]]; then [ -n "${STUB_RULES_CONFIGURED:-}" ] && echo "configmap/company-dns-rules configured" || echo "configmap/company-dns-rules unchanged"
  elif [[ "$args" == *"-f -"* ]]; then [ -n "${STUB_DEPLOYMENT_CONFIGURED:-}" ] && echo "deployment.apps/company-dns configured" || echo "deployment.apps/company-dns unchanged"
  else echo "object unchanged"; fi
fi
case "$args" in
  "config current-context") echo stub-context;;
  "get nodes -o name") [ -n "${STUB_NO_CLUSTER:-}" ] && exit 1; echo node/cafe-1;;
  "get ingressclass traefik") [ -n "${STUB_NO_INGRESSCLASS:-}" ] && exit 1;;
  "get clusterissuer letsencrypt-prod") [ -n "${STUB_NO_ISSUER:-}" ] && exit 1;;
  "get svc -A --no-headers")
    [ -n "${STUB_NO_CONTROLLER:-}" ] && exit 0
    printf 'kube-system   sealed-secrets-controller-metrics   ClusterIP   10.0.0.1   <none>   8081/TCP   1d\n'
    printf 'kube-system   sealed-secrets-controller   ClusterIP   10.0.0.2   <none>   8080/TCP   1d\n'
    # a real cluster lists far more services than fit in a pipe buffer, after the match
    [ -n "${STUB_BIG_SVC:-}" ] && for i in $(seq 1 6000); do printf 'ns%d   svc-%d   ClusterIP   10.1.%d.%d   <none>   80/TCP   1d\n' $i $i $((i / 250)) $((i % 250)); done;;
  *"get secret company-dns-credentials"*) [ "${STUB_SECRET:-present}" = missing ] && exit 1; echo secret;;
  *"get ingress company-dns -o jsonpath"*) [ -n "${STUB_NO_LB:-}" ] && exit 0; echo 192.168.1.200;;
  *"get certificate company-dns-staging-io-tls -o jsonpath"*)
    if [ -n "${STUB_CERT_FALSE_POLLS:-}" ]; then
      n=$(cat "$S/cert-polls" 2>/dev/null || echo 0); echo $((n + 1)) > "$S/cert-polls"
      if [ "$n" -lt "$STUB_CERT_FALSE_POLLS" ]; then echo False; else echo True; fi
    else echo "${STUB_CERT_READY:-True}"; fi;;
  *"get certificate company-dns-staging-io-tls"*)
    [ -n "${STUB_FIRST:-}" ] && [ ! -f "$S/cert.applied" ] && exit 1; echo certificate;;
  *"apply"*"certificate.yaml"*) touch "$S/cert.applied";;
  *"get deployment company-dns -o go-template"*)
    key="$(echo "$args" | sed -E 's|.*mediumroast.io/([a-z-]+).*|\1|')"
    var="STUB_ANNOT_$(echo "$key" | tr 'a-z-' 'A-Z_')"
    echo "${!var:-<no value>}";;
  *"jsonpath={.spec.template.spec.containers[0].image}"*)
    if [ -f "$S/deploy.stdin" ]; then grep -m1 'image:' "$S/deploy.stdin" | sed 's/.*image: *//'; else echo "${STUB_RUNNING_IMAGE:-}"; fi;;
  *"jsonpath={.spec.replicas}"*) echo 2;;
  *"jsonpath={.status.readyReplicas}"*) echo "${STUB_READY:-2}";;
  *"rollout status"*) [ "${STUB_ROLLOUT:-ok}" = fail ] && exit 1;;
  *"rollout restart"*) :;;
  *"rollout undo"*) [ "${STUB_UNDO:-ok}" = fail ] && exit 1;;
  *"create secret generic"*)
    for a in "$@"; do case "$a" in --from-file=*) cp "${a#--from-file=credentials=}" "$S/secret-source";; esac; done
    printf 'kind: Secret\n';;
  *"get deployment company-dns"*) [ -n "${STUB_NO_DEPLOYMENT:-}" ] && exit 1; echo deployment;;
esac
exit 0
'''
CURL = r'''#!/usr/bin/env bash
S="$STUB_STATE"
echo "curl $*" >> "$S/calls.log"
args="$*"
case "$args" in *api.github.com/user*) echo '{"login": "tester"}'; exit 0;; esac
auth=0
if [[ "$args" == *" -u "* ]]; then auth=1; fi
if [[ "$args" == *" -K - "* ]]; then cat > "$S/curl-config"; auth=1; fi   # credentials on stdin: kept out of the call log
if [[ "$args" == *" -w "* ]]; then
  if [[ "$args" == *"/V4.0/sql"* ]]; then
    if [[ $auth -eq 1 ]]; then printf '%s' "${STUB_AUTH_CODE:-200}"; else printf '%s' "${STUB_ANON_CODE:-401}"; fi
  else printf 200; fi
  exit 0
fi
[ "${STUB_SMOKE:-ok}" = fail ] && [[ "$args" == *"127.0.0.1:18089"* ]] && exit 22
# a real lookup answer is much longer than the 120 characters the script shows
if [ -n "${STUB_BIG_BODY:-}" ] && [[ "$args" == *"/V4.0/na/sic/code"* ]]; then for i in $(seq 1 400); do printf '{"code":"3571","description":"Electronic Computers and related things %d"}' $i; done; exit 0; fi
echo '{}'
exit 0
'''
DOCKER = r'''#!/usr/bin/env bash
S="$STUB_STATE"
echo "docker $* [DOCKER_CONFIG=${DOCKER_CONFIG:-}]" >> "$S/calls.log"
case "$1" in
  buildx) [ -n "${STUB_NO_BUILDX:-}" ] && exit 1;;
  info) [[ "$*" == *"--format"* ]] && echo /tmp;;
  login) cat >/dev/null;;
  pull)
    if [ "${STUB_PULL:-ok}" = never ]; then echo "Error response from daemon: denied" >&2; exit 1; fi
    n=$(cat "$S/pulls" 2>/dev/null || echo 0); echo $((n + 1)) > "$S/pulls"
    [ "$n" -lt "${STUB_PULL_FAILS:-0}" ] && { echo "Error response from daemon: denied" >&2; exit 1; };;
  inspect) echo "ghcr.io/miha42-github/company_dns/company_dns_v4@sha256:abc123";;
esac
exit 0
'''
KUBESEAL = r'''#!/usr/bin/env bash
echo "kubeseal $*" >> "$STUB_STATE/calls.log"
cat > "$STUB_STATE/kubeseal-stdin"
case "${STUB_SEAL:-ok}" in
  bad) echo "oops"; exit 0;;
  clusterwide) printf 'kind: SealedSecret\nmetadata:\n  annotations:\n    sealedsecrets.bitnami.com/cluster-wide: "true"\n'; exit 0;;
esac
printf 'apiVersion: bitnami.com/v1alpha1\nkind: SealedSecret\nmetadata:\n  name: company-dns-credentials\n  namespace: company-dns-staging\nspec:\n  encryptedData:\n    credentials: AgBy3i4OJSWK%s\n' "$RANDOM"
'''
PYTHON = '''#!/usr/bin/env bash
if [ "$1" = "-c" ] && [[ "$2" == *gethostbyname* ]]; then [ "${STUB_DNS:-ok}" = fail ] && exit 1; echo "${STUB_DNS_IP:-192.168.1.200}"; exit 0; fi
exec "%s" "$@"
''' % sys.executable
OPENSSL = '''#!/usr/bin/env bash
[ "${STUB_OPENSSL:-ok}" = fail ] && exit 1
exec /usr/bin/openssl "$@"
'''
BUILD_STUB = '#!/usr/bin/env bash\necho "$(basename "$0") $* [MODEL_DIR=${MODEL_DIR:-}]" >> "$STUB_STATE/calls.log"\n[ "${STUB_BUILD:-ok}" = fail ] && [[ "$(basename "$0")" == docker-build.sh ]] && exit 1\n[ "${STUB_SMOKE_IMAGE:-ok}" = fail ] && [[ "$(basename "$0")" == docker-smoke.sh ]] && exit 1\nexit 0\n'
SUITE_STUB = '''#!/usr/bin/env python3
import json, os, socket, sys
try:
    resolved = socket.getaddrinfo("company-dns-staging.mediumroast.io", 443)[0][4][0]
except OSError:
    resolved = None
open(os.environ["STUB_STATE"] + "/suite.json", "w").write(json.dumps({"argv": sys.argv[1:], "resolved": resolved, "env": {k: os.environ.get(k) for k in ("BASE_URL", "API_TESTS_PROFILE", "API_TESTS_TOKEN")}}))
sys.exit(1 if os.environ.get("STUB_SUITE_FAIL") else 0)
'''


def exe(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.state = self.tmp / "state"
        self.state.mkdir()
        (self.state / "calls.log").write_text("")
        self.bin = self.tmp / "bin"
        for name, body in (("kubectl", KUBECTL), ("curl", CURL), ("docker", DOCKER), ("kubeseal", KUBESEAL), ("python3", PYTHON), ("openssl", OPENSSL)):
            exe(self.bin / name, body)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.secrets = self.home / "company_dns-staging-secrets"
        self.env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "STUB_STATE": str(self.state), "HOME": str(self.home),
                    "V4_POLL_SECS": "0", "V4_WAIT_PUBLIC_SECS": "3", "V4_WAIT_CERT_SECS": "3", "V4_WAIT_SECRET_TRIES": "2", "V4_SECRET_POLL_SECS": "0", "V4_SMOKE_TRIES": "1"}
        for var in [v for v in self.env if v.startswith(("DATA_DIR", "MODEL_DIR", "COMPANY_DNS", "V4_SECRETS", "SEALED_SECRETS"))]:
            del self.env[var]
        # a throwaway repository: the scripts, the real staging manifests, stub build scripts, the data and model the preflight looks for
        self.repo = self.tmp / "repo"
        for name in (DEPLOY_SH, SEAL_SH):
            shutil.copy(REPO / "scripts" / name, self.repo / "scripts" / name) if (self.repo / "scripts").exists() else (self.repo / "scripts").mkdir(parents=True) or shutil.copy(REPO / "scripts" / name, self.repo / "scripts" / name)
        shutil.copytree(REPO / "k8s/staging", self.repo / "k8s/staging")
        # the real sealed secret is committed now; the tests start from a repository without one (the Deploy tests add a stand-in)
        (self.repo / "k8s/staging/sealedsecret-credentials.yaml").unlink(missing_ok=True)
        exe(self.repo / "v4/scripts/docker-build.sh", BUILD_STUB)
        exe(self.repo / "v4/scripts/docker-smoke.sh", BUILD_STUB)
        exe(self.repo / "api_tests/run.py", SUITE_STUB)
        (self.repo / "tmp/.fastembed_cache").mkdir(parents=True)
        (self.repo / "tmp/us_flat.feather").write_text("x")
        (self.repo / ".env").write_text("GITHUB_PAT=ghp_test\n")
        (self.repo / ".gitignore").write_text(".env\ntmp/\nv4/.build-log\nv4/.staging-suite.json\n")
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "x")

    def git(self, *a):
        genv = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        return subprocess.run(["git", *a], cwd=self.repo, check=True, capture_output=True, text=True, env=genv)

    def add_sealed(self):
        (self.repo / "k8s/staging/sealedsecret-credentials.yaml").write_text("kind: SealedSecret\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "sealed")

    def run_script(self, name, *args, **env):
        return subprocess.run([str(self.repo / "scripts" / name), *args], cwd=self.repo, env={**self.env, **env}, capture_output=True, text=True)

    def calls(self) -> list[str]:
        return (self.state / "calls.log").read_text().splitlines()

    def kubectl_calls(self):
        return [c for c in self.calls() if c.startswith("kubectl ")]

    def index(self, needle, start=0):
        return next(i for i, l in enumerate(self.calls()) if i >= start and needle in l)

    def write_tokens(self, profile="staging-test", token="tok123"):
        self.secrets.mkdir(parents=True, exist_ok=True)
        (self.secrets / "tokens").write_text(f"{profile}:{token}\n")


class Deploy(Base):
    def setUp(self):
        super().setUp()
        self.add_sealed()

    def run_script(self, *args, **env):
        return super().run_script(DEPLOY_SH, *args, **env)

    # ----------------------------------------------------------- preflight
    def test_check_passes_when_everything_is_in_place_and_changes_nothing(self):
        r = self.run_script("--check")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Preflight passed", r.stdout)
        calls = "\n".join(self.calls())
        for forbidden in ("docker login", "docker push", " apply ", "annotate"):
            self.assertNotIn(forbidden, calls)

    def test_check_lists_every_problem_at_once(self):
        (self.repo / ".env").unlink()
        shutil.rmtree(self.repo / "tmp")
        self.git("rm", "-q", "-f", "k8s/staging/sealedsecret-credentials.yaml")
        self.git("commit", "-q", "-m", "no sealed")
        r = self.run_script("--check", STUB_SECRET="missing", STUB_DNS="fail", STUB_NO_BUILDX="1", STUB_NO_ISSUER="1", STUB_NO_INGRESSCLASS="1")
        self.assertEqual(r.returncode, 1)
        for fragment in (".env", "GITHUB_PAT", "buildx", "data directory", "embedding model", "ingress class", "ClusterIssuer", "no credentials", "does not resolve"):
            self.assertIn(fragment, r.stderr, fragment)

    def test_a_public_address_for_the_host_warns_about_the_certificate_check_but_does_not_stop(self):
        # regression from the first real run: the host resolved to the public address, cert-manager's self-check from inside the cluster timed out
        r = self.run_script("--check", STUB_DNS_IP="75.80.225.46")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("75.80.225.46", r.stderr)
        self.assertIn("hairpin", r.stderr)
        self.assertIn("192.168.1.200", r.stderr)
        r = self.run_script("--check", STUB_DNS_IP="192.168.1.200")
        self.assertNotIn("hairpin", r.stderr)

    def test_an_unreachable_cluster_is_reported(self):
        r = self.run_script("--check", STUB_NO_CLUSTER="1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not reachable", r.stderr)

    def test_a_dirty_tree_is_refused_unless_allowed(self):
        (self.repo / "k8s/staging/namespace.yaml").write_text("changed\n")
        r = self.run_script("--check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("uncommitted", r.stderr)
        r = self.run_script("--check", "--allow-dirty")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"tag would be \d{8}-[0-9a-f]{7}-dirty")

    def test_the_tag_is_pinned_and_a_plain_docker_tag(self):
        for bad in ("latest", "a b", "a;b"):
            self.assertEqual(self.run_script(bad).returncode, 2, bad)
        self.assertEqual(self.run_script("--no-build").returncode, 2, "--no-build needs a tag")
        self.assertEqual([c for c in self.calls() if c.startswith(("docker", "kubectl"))], [])

    # ----------------------------------------------------------- the full run
    def test_a_full_run_builds_pushes_checks_the_pull_and_deploys_in_order(self):
        r = self.run_script("10112026-abc1234")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("unexpected failure", r.stderr, "the failure trap must not fire on handled failures")
        order = ["docker login", "docker-build.sh", "docker-smoke.sh", "docker push", "docker pull", "namespace.yaml", "sealedsecret-credentials.yaml",
                 "configmap-rules.yaml", "configmap-loglevel.yaml", "apply -f -", "rollout status", "port-forward", "middleware-redirect.yaml",
                 "ingress.yaml", "certificate.yaml", "annotate"]
        last = -1
        for step in order:
            i = self.index(step, last + 1)
            self.assertGreater(i, last, step)
            last = i

    def test_the_build_is_the_small_amd64_image_with_the_model_found_in_tmp(self):
        self.run_script("10112026-abc1234")
        build = next(c for c in self.calls() if c.startswith("docker-build.sh"))
        self.assertIn("-t ghcr.io/miha42-github/company_dns/company_dns_v4:10112026-abc1234", build)
        self.assertIn("-p release-small", build)
        self.assertIn("--platform linux/amd64", build)
        self.assertIn(f"MODEL_DIR={self.repo.resolve() / 'tmp/.fastembed_cache'}", build.replace(str(self.repo), str(self.repo.resolve())))

    def test_a_failed_build_or_smoke_test_stops_before_anything_is_pushed_or_applied(self):
        for knob in ("STUB_BUILD", "STUB_SMOKE_IMAGE"):
            (self.state / "calls.log").write_text("")
            r = self.run_script("10112026-abc1234", **{knob: "fail"})
            self.assertNotEqual(r.returncode, 0, knob)
            joined = "\n".join(self.calls())
            self.assertNotIn("docker push", joined)
            self.assertNotIn("kubectl apply", joined.replace("kubectl get", ""))

    def test_only_the_staging_namespace_is_touched_and_nothing_is_deleted(self):
        self.run_script("10112026-abc1234")
        calls = self.kubectl_calls()
        self.assertEqual({m for c in calls for m in re.findall(r" -n (\S+)", c)}, {"company-dns-staging"})
        for c in calls:
            self.assertNotIn(" delete", c)
            self.assertNotIn("--all-namespaces", c)
        for f in re.findall(r"apply (?:--dry-run=server )?-f (\S+)", "\n".join(calls)):
            if f != "-":
                self.assertIn("k8s/staging/", f)

    def test_the_tag_goes_into_the_applied_deployment_and_the_repository_is_left_alone(self):
        before = (self.repo / "k8s/staging/deployment.yaml").read_text()
        r = self.run_script("10112026-abc1234")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        applied = (self.state / "deploy.stdin").read_text()
        self.assertEqual([l.strip() for l in applied.splitlines() if l.strip().startswith("image:")],
                         ["image: ghcr.io/miha42-github/company_dns/company_dns_v4:10112026-abc1234"])
        self.assertEqual((self.repo / "k8s/staging/deployment.yaml").read_text(), before)
        self.assertIn("UNSET", before)
        self.assertEqual(self.git("status", "--porcelain").stdout, "", "a deploy must leave nothing to commit")

    def test_the_deployment_is_stamped_with_what_is_running_and_the_log_is_appended(self):
        self.run_script("10112026-abc1234")
        annotate = next(c for c in self.calls() if " annotate " in c)
        self.assertIn("-n company-dns-staging annotate deployment company-dns --overwrite", annotate)
        self.assertIn("company-dns.mediumroast.io/deployed-tag=10112026-abc1234", annotate)
        self.assertIn("company-dns.mediumroast.io/commit=" + self.git("rev-parse", "--short=7", "HEAD").stdout.strip(), annotate)
        self.assertIn("company-dns.mediumroast.io/digest=ghcr.io/miha42-github/company_dns/company_dns_v4@sha256:abc123", annotate)
        rec = json.loads((self.repo / "v4/.build-log").read_text().strip().splitlines()[-1])
        self.assertEqual((rec["tag"], rec["built"], rec["namespace"]), ("10112026-abc1234", True, "company-dns-staging"))

    def test_the_default_tag_is_the_date_and_the_commit(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        sha = self.git("rev-parse", "--short=7", "HEAD").stdout.strip()
        self.assertRegex(next(c for c in self.calls() if c.startswith("docker push")), rf"company_dns_v4:\d{{8}}-{sha}")

    # ----------------------------------------------------------- the private package
    def test_it_waits_for_the_package_to_be_made_public_and_then_continues(self):
        r = self.run_script("10112026-abc1234", STUB_PULL_FAILS="2")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Change visibility", r.stdout)
        self.assertIn("https://github.com/miha42-github?tab=packages", r.stdout)
        self.assertIn("company_dns%2Fcompany_dns_v4", r.stdout, "the link must name the V4 package, not V3's")
        self.assertIn("The anonymous pull said: Error response from daemon: denied", r.stdout)
        self.assertGreaterEqual(len([c for c in self.calls() if c.startswith("docker pull")]), 3)
        self.assertFalse(any("DOCKER_CONFIG=]" in c for c in self.calls() if c.startswith("docker pull")), "the check must use an empty Docker config")

    def test_a_package_that_never_becomes_public_stops_before_the_deploy(self):
        r = self.run_script("10112026-abc1234", STUB_PULL="never")
        self.assertEqual(r.returncode, 1)
        self.assertIn("--no-build 10112026-abc1234", r.stderr)
        self.assertIn("denied", r.stdout, "the registry's own answer is shown, not hidden")
        self.assertNotIn("namespace.yaml", "\n".join(self.calls()))

    # ----------------------------------------------------------- applying and verifying
    def test_a_missing_credentials_secret_stops_before_the_workload(self):
        r = self.run_script("10112026-abc1234", STUB_SECRET="missing")
        self.assertEqual(r.returncode, 1)
        self.assertIn("company-dns-credentials", r.stderr)
        joined = "\n".join(self.calls())
        self.assertNotIn("apply -f -", joined)
        self.assertNotIn("ingress.yaml", joined)

    def test_a_real_sized_lookup_answer_does_not_fail_the_smoke_test(self):
        # regression: `curl | head -c 120` under pipefail failed whenever the answer was longer than 120 bytes
        r = self.run_script("10112026-abc1234", STUB_BIG_BODY="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("a SIC lookup ok", r.stdout)

    def test_a_failed_smoke_test_means_the_ingress_is_never_applied(self):
        r = self.run_script("10112026-abc1234", STUB_SMOKE="fail")
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("ingress.yaml", "\n".join(self.calls()))

    def test_a_failed_rollout_is_rolled_back_automatically(self):
        r = self.run_script("10112026-abc1234", STUB_ROLLOUT="fail")
        self.assertEqual(r.returncode, 1)
        self.assertIn("rolled back", r.stderr)
        self.assertTrue(any("rollout undo deployment/company-dns" in c for c in self.kubectl_calls()))
        self.assertNotIn("ingress.yaml", "\n".join(self.calls()))
        self.assertNotIn("annotate", "\n".join(self.calls()))

    def test_a_failed_first_rollout_says_there_is_nothing_to_roll_back_to(self):
        r = self.run_script("10112026-abc1234", STUB_ROLLOUT="fail", STUB_UNDO="fail")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no earlier revision", r.stderr)

    def test_the_first_run_waits_for_the_certificate_and_a_late_one_is_reported(self):
        r = self.run_script("10112026-abc1234", STUB_FIRST="1", STUB_CERT_FALSE_POLLS="2")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("First deployment detected", r.stdout)
        self.assertIn("Waiting for the certificate", r.stdout)
        (self.state / "calls.log").write_text("")
        (self.state / "cert.applied").unlink()
        r = self.run_script("10112026-abc1234", STUB_FIRST="1", STUB_CERT_READY="False")
        self.assertEqual(r.returncode, 1)
        self.assertIn("certificate is not ready", r.stderr)
        self.assertIn("up and verified", r.stderr)

    def test_a_routine_run_with_a_ready_certificate_does_not_wait(self):
        r = self.run_script("10112026-abc1234")
        self.assertNotIn("Waiting for the certificate", r.stdout)

    def test_a_rerun_before_the_certificate_is_ready_waits_for_it_too(self):
        # the first real run: the script timed out on the certificate; the re-run (not a first run any more) must wait, not verify against Traefik's default certificate
        r = self.run_script("--no-build", "10112026-abc1234", STUB_CERT_FALSE_POLLS="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Waiting for the certificate", r.stdout)

    def test_https_verification_goes_through_traefiks_lan_address_with_time_limits(self):
        # regression from the first real run: checking by name from a node hit the unreachable public address and hung for 133 seconds
        r = self.run_script("10112026-abc1234")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        https = [c for c in self.calls() if c.startswith("curl") and "https://company-dns-staging.mediumroast.io" in c]
        self.assertGreaterEqual(len(https), 3)
        for c in https:
            self.assertIn("--resolve company-dns-staging.mediumroast.io:443:192.168.1.200", c)
            self.assertIn("--max-time 20", c)
            self.assertIn("--connect-timeout 5", c)
        self.assertIn("via Traefik at 192.168.1.200", r.stdout)
        (self.state / "calls.log").write_text("")
        r = self.run_script("10112026-abc1234", STUB_NO_LB="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("--resolve", "\n".join(c for c in self.calls() if c.startswith("curl")))
        self.assertIn("--max-time 20", "\n".join(c for c in self.calls() if c.startswith("curl")))

    def test_https_verification_wants_401_without_credentials_and_200_with_them(self):
        self.write_tokens()
        r = self.run_script("10112026-abc1234")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("401 (as it should)", r.stdout)
        self.assertIn("as staging-test: 200", r.stdout)
        r = self.run_script("10112026-abc1234", STUB_ANON_CODE="200")
        self.assertEqual(r.returncode, 1)
        self.assertIn("expected 401", r.stderr)
        r = self.run_script("10112026-abc1234", STUB_AUTH_CODE="401")
        self.assertEqual(r.returncode, 1)
        self.assertIn("same run", r.stderr)

    def test_without_a_token_file_the_authenticated_check_is_skipped_and_says_so(self):
        r = self.run_script("10112026-abc1234")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("authenticated check is skipped", r.stdout)

    # ----------------------------------------------------------- the suite
    def test_the_suite_gets_its_token_through_the_environment_never_the_command_line(self):
        self.write_tokens(token="s3cr3tT0ken")
        r = self.run_script("10112026-abc1234", "--suite")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        run = json.loads((self.state / "suite.json").read_text())
        self.assertEqual(run["env"], {"BASE_URL": "https://company-dns-staging.mediumroast.io", "API_TESTS_PROFILE": "staging-test", "API_TESTS_TOKEN": "s3cr3tT0ken"})
        self.assertEqual(run["argv"][:2], ["--layers", "L0,L1,L2,L4"])
        self.assertNotIn("s3cr3tT0ken", " ".join(run["argv"]))
        self.assertNotIn("s3cr3tT0ken", "\n".join(self.calls()) + r.stdout + r.stderr, "the token must not appear in any command line, including curl's")
        self.assertIn("s3cr3tT0ken", (self.state / "curl-config").read_text(), "curl gets the credentials on its standard input")

    def test_the_suite_resolves_the_staging_name_to_traefik_for_its_own_process_only(self):
        # regression from the first real run: the suite ran by name from a node that cannot reach the public address, and every test was skipped with "timed out"
        self.write_tokens()
        r = self.run_script("10112026-abc1234", "--suite")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        run = json.loads((self.state / "suite.json").read_text())
        self.assertEqual(run["resolved"], "192.168.1.200")
        self.assertEqual(run["env"]["BASE_URL"], "https://company-dns-staging.mediumroast.io", "TLS and routing keep using the real host name")
        self.assertEqual(run["argv"][:2], ["--layers", "L0,L1,L2,L4"])
        self.assertFalse(any("/etc/hosts" in c for c in self.calls()), "nothing on the machine is edited")

    def test_a_failing_suite_is_reported_as_a_suite_failure_not_an_unexpected_one(self):
        # regression: the first real --suite run ended with "unexpected failure at line ..." instead of saying the tests failed
        self.write_tokens()
        r = self.run_script("10112026-abc1234", "--suite", STUB_SUITE_FAIL="1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("the API test suite reported failures", r.stderr)
        self.assertNotIn("unexpected failure", r.stderr)
        self.assertIn("is running", r.stdout, "the deployment summary still prints")

    def test_changed_rules_restart_the_pods_when_the_deployment_itself_did_not_change(self):
        # regression: a change to the profiles' rules was applied to the ConfigMap but the pods kept the old rules until something else restarted them
        r = self.run_script("10112026-abc1234", STUB_RULES_CONFIGURED="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("restarting the pods", r.stdout)
        i_restart = self.index("rollout restart deployment/company-dns")
        self.assertLess(self.index("apply -f -"), i_restart)
        self.assertLess(i_restart, self.index("rollout status"))

    def test_no_restart_when_nothing_changed_or_the_deployment_is_rolling_anyway(self):
        self.run_script("10112026-abc1234")
        self.assertNotIn("rollout restart", "\n".join(self.calls()))
        (self.state / "calls.log").write_text("")
        self.run_script("10112026-abc1234", STUB_RULES_CONFIGURED="1", STUB_DEPLOYMENT_CONFIGURED="1")
        self.assertNotIn("rollout restart", "\n".join(self.calls()))

    def test_the_suite_is_off_by_default_and_skipped_without_a_token(self):
        self.write_tokens()
        self.run_script("10112026-abc1234")
        self.assertFalse((self.state / "suite.json").exists())
        (self.secrets / "tokens").unlink()
        r = self.run_script("10112026-abc1234", "--suite")
        self.assertFalse((self.state / "suite.json").exists())
        self.assertIn("--suite skipped", r.stderr)

    # ----------------------------------------------------------- other modes
    def test_status_reports_what_is_running_and_changes_nothing(self):
        r = self.run_script("--status", STUB_ANNOT_DEPLOYED_TAG="10102026-abc1234", STUB_ANNOT_COMMIT="abc1234", STUB_ANNOT_DIGEST="sha256:ff", STUB_ANNOT_DEPLOYED_AT="2026-10-10T20:00:00Z")
        self.assertEqual(r.returncode, 0, r.stderr)
        for fragment in ("10102026-abc1234", "abc1234", "sha256:ff", "2026-10-10T20:00:00Z"):
            self.assertIn(fragment, r.stdout)
        joined = "\n".join(self.calls())
        for forbidden in (" apply ", "annotate", "rollout", "docker "):
            self.assertNotIn(forbidden, joined)

    def test_status_says_so_when_nothing_is_deployed(self):
        r = self.run_script("--status", STUB_NO_DEPLOYMENT="1")
        self.assertEqual(r.returncode, 0)
        self.assertIn("nothing is deployed", r.stdout)

    def test_status_does_not_claim_nothing_is_deployed_when_the_cluster_is_unreachable(self):
        r = self.run_script("--status", STUB_NO_CLUSTER="1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not reachable", r.stderr)
        self.assertNotIn("nothing is deployed", r.stdout)

    def test_no_build_deploys_a_pushed_tag_without_touching_docker(self):
        r = self.run_script("--no-build", "10102026-abc1234")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual([c for c in self.calls() if c.startswith(("docker", "curl -sf"))], [])
        self.assertIn("company_dns_v4:10102026-abc1234", (self.state / "deploy.stdin").read_text())

    def test_no_build_does_not_need_the_build_prerequisites(self):
        (self.repo / ".env").unlink()
        shutil.rmtree(self.repo / "tmp")
        r = self.run_script("--no-build", "10102026-abc1234", STUB_NO_BUILDX="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_rollback_without_a_tag_undoes_the_rollout_and_with_a_tag_deploys_it(self):
        r = self.run_script("--rollback", STUB_RUNNING_IMAGE="x:10092026-aaaaaaa")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(any("rollout undo deployment/company-dns" in c for c in self.kubectl_calls()))
        self.assertFalse((self.state / "deploy.stdin").exists())
        self.assertFalse(any(c.startswith("docker") for c in self.calls()))
        (self.state / "calls.log").write_text("")
        r = self.run_script("--rollback", "10092026-aaaaaaa")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("rollout undo", "\n".join(self.calls()))
        self.assertIn("company_dns_v4:10092026-aaaaaaa", (self.state / "deploy.stdin").read_text())

    def test_a_dry_run_changes_nothing(self):
        r = self.run_script("--dry-run", "10112026-abc1234")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        applies = [c for c in self.kubectl_calls() if " apply " in c]
        self.assertGreaterEqual(len(applies), 9)
        for c in applies:
            self.assertIn("--dry-run=server", c)
        joined = "\n".join(self.calls())
        for forbidden in ("annotate", "rollout", "docker login", "docker push", "docker-build"):
            self.assertNotIn(forbidden, joined)
        self.assertFalse((self.repo / "v4/.build-log").exists())

    def test_not_every_replica_ready_is_a_failure(self):
        r = self.run_script("10112026-abc1234", STUB_READY="1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not every replica is ready", r.stderr)


class Seal(Base):
    def run_script(self, *args, **env):
        return super().run_script(SEAL_SH, *args, **env)

    def read(self, name):
        return (self.secrets / name).read_text()

    def tokens(self):
        return dict(l.split(":", 1) for l in self.read("tokens").splitlines())

    def test_a_token_and_a_matching_hash_for_every_profile_the_rules_name(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("unexpected failure", r.stderr)
        tokens = self.tokens()
        self.assertEqual(set(tokens), {"mediumroast.io", "staging-test"})
        hashes = dict(l.split(":", 1) for l in self.read("credentials").splitlines() if not l.startswith("#"))
        self.assertEqual(set(hashes), set(tokens))
        for p, t in tokens.items():
            self.assertRegex(t, r"^[0-9a-f]{64}$")
            self.assertEqual(hashes[p], hashlib.sha256(t.encode()).hexdigest())

    def test_the_files_are_private_and_no_token_is_printed(self):
        r = self.run_script()
        for name in ("tokens", "credentials"):
            self.assertEqual(stat.S_IMODE((self.secrets / name).stat().st_mode), 0o600, name)
        self.assertEqual(stat.S_IMODE(self.secrets.stat().st_mode), 0o700)
        for t in self.tokens().values():
            self.assertNotIn(t, r.stdout + r.stderr + "\n".join(self.calls()))

    def test_tokens_are_kept_and_rotate_replaces_them(self):
        self.run_script()
        first = self.tokens()
        self.run_script()
        self.assertEqual(self.tokens(), first)
        self.run_script("--rotate")
        rotated = self.tokens()
        self.assertEqual(set(rotated), set(first))
        for p in first:
            self.assertNotEqual(rotated[p], first[p])

    def test_it_refuses_to_write_secrets_inside_the_repository(self):
        inside = self.repo / "secrets"
        r = self.run_script("--out", str(inside))
        self.assertEqual(r.returncode, 1)
        self.assertIn("inside the repository", r.stderr)
        self.assertFalse(inside.exists())

    def test_the_controller_is_found_in_the_cluster_and_the_metrics_service_is_not_chosen(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("kube-system/sealed-secrets-controller", r.stdout)
        seal = next(c for c in self.calls() if c.startswith("kubeseal"))
        self.assertIn("--controller-namespace kube-system --controller-name sealed-secrets-controller --format yaml", seal)
        self.assertIn("kubectl create secret generic company-dns-credentials -n company-dns-staging", "\n".join(self.calls()))

    def test_a_cluster_with_thousands_of_services_still_finds_the_controller(self):
        # regression: awk's early exit closed the pipe, kubectl died of SIGPIPE, and pipefail made the script exit silently (status 141) before creating anything
        for _ in range(3):
            r = self.run_script(STUB_BIG_SVC="1")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("kube-system/sealed-secrets-controller", r.stdout)
        self.assertTrue((self.secrets / "tokens").exists())
        self.assertTrue((self.repo / "k8s/staging/sealedsecret-credentials.yaml").exists())

    def test_an_unexpected_failure_is_never_silent(self):
        r = self.run_script(STUB_OPENSSL="fail")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unexpected failure", r.stderr)
        self.assertIn("line", r.stderr)

    def test_flags_override_the_discovered_controller(self):
        self.run_script("--controller-namespace", "sealed", "--controller-name", "ctl")
        self.assertIn("--controller-namespace sealed --controller-name ctl", next(c for c in self.calls() if c.startswith("kubeseal")))
        self.assertNotIn("get svc", "\n".join(self.calls()))

    def test_no_controller_found_says_how_to_find_it(self):
        r = self.run_script(STUB_NO_CONTROLLER="1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("--controller-namespace", r.stderr)

    def test_the_sealed_file_is_made_from_the_credentials_and_holds_no_token(self):
        self.run_script()
        sealed = (self.repo / "k8s/staging/sealedsecret-credentials.yaml").read_text()
        self.assertIn("kind: SealedSecret", sealed)
        self.assertEqual((self.state / "secret-source").read_text(), self.read("credentials"))
        for t in self.tokens().values():
            self.assertNotIn(t, sealed)

    def test_unchanged_credentials_are_not_sealed_again_unless_asked(self):
        self.run_script()
        sealed = (self.repo / "k8s/staging/sealedsecret-credentials.yaml").read_text()
        r = self.run_script()
        self.assertIn("unchanged", r.stdout)
        self.assertEqual((self.repo / "k8s/staging/sealedsecret-credentials.yaml").read_text(), sealed)
        self.run_script("--reseal")
        self.assertNotEqual((self.repo / "k8s/staging/sealedsecret-credentials.yaml").read_text(), sealed)
        self.run_script("--rotate")
        self.assertEqual(len([c for c in self.calls() if c.startswith("kubeseal")]), 3)

    def test_a_bad_or_wide_scoped_result_is_not_left_behind(self):
        for knob in ("bad", "clusterwide"):
            r = self.run_script(STUB_SEAL=knob)
            self.assertEqual(r.returncode, 1, knob)
            self.assertFalse((self.repo / "k8s/staging/sealedsecret-credentials.yaml").exists(), knob)

    def test_apply_applies_the_namespace_then_the_sealed_secret_and_waits_for_the_secret(self):
        r = self.run_script("--apply")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertLess(self.index("namespace.yaml"), self.index("sealedsecret-credentials.yaml"))
        self.assertLess(self.index("sealedsecret-credentials.yaml"), self.index("get secret company-dns-credentials"))
        r = self.run_script("--apply", STUB_SECRET="missing")
        self.assertEqual(r.returncode, 1)
        self.assertIn("did not appear", r.stderr)

    def test_without_apply_nothing_is_applied(self):
        self.run_script()
        self.assertNotIn(" apply ", "\n".join(self.calls()))

    def test_the_preflight_lists_what_is_missing_at_once(self):
        # no kubeseal and no cluster: both are reported together
        (self.bin / "kubeseal").unlink()
        r = self.run_script(STUB_NO_CLUSTER="1", PATH=f"{self.bin}:/usr/bin:/bin")
        self.assertEqual(r.returncode, 1)
        self.assertIn("kubeseal is not installed", r.stderr)
        self.assertIn("not reachable", r.stderr)

    def test_only_the_staging_namespace_is_touched(self):
        self.run_script("--apply")
        namespaces = {m for c in self.kubectl_calls() for m in re.findall(r" -n (\S+)", c)}
        self.assertEqual(namespaces, {"company-dns-staging"})
        self.assertNotIn(" delete", "\n".join(self.calls()))


if __name__ == "__main__":
    unittest.main()
