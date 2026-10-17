"""Checks on k8s/prod-v4/ that need no cluster. Run: python3 -m unittest k8s/test_prod_v4_manifests.py

V4 runs in production's namespace beside V3 and takes no traffic until the cutover moves the Ingress backend (docs/plans/v4-production-cutover.md, D1, WP2).
Two things must never drift: V4's pods must not be selected by V3's Service (V3 listens on 8000, V4 on 4000), and V4 must stay the proven staging container
except where production deliberately differs (no SQL endpoint, its own secret and ConfigMaps). Needs PyYAML (skipped without it).
"""
import json
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

K8S = Path(__file__).resolve().parent
DIR = K8S / "prod-v4"
NS = "company-dns"
V3_LABEL = "company-dns"
V4_LABEL = "company-dns-v4"
IMAGE_PREFIX = "ghcr.io/miha42-github/company_dns/company_dns_v4:"


def load(directory: Path) -> list[dict]:
    docs = []
    for f in sorted(directory.glob("*.yaml")):
        docs += [d for d in yaml.safe_load_all(f.read_text()) if d]
    return docs


def of_kind(docs, kind):
    return [d for d in docs if d["kind"] == kind]


def env_of(container) -> dict:
    return {e["name"]: e.get("value") for e in container["env"]}


@unittest.skipIf(yaml is None, "PyYAML not installed")
class ProductionV4Manifests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = load(DIR)
        cls.dep = of_kind(cls.docs, "Deployment")[0]
        cls.pod = cls.dep["spec"]["template"]["spec"]
        cls.c = cls.pod["containers"][0]
        cls.svc = of_kind(cls.docs, "Service")[0]
        cls.staging = load(K8S / "staging")
        cls.staging_c = of_kind(cls.staging, "Deployment")[0]["spec"]["template"]["spec"]["containers"][0]

    def test_everything_lives_in_the_production_namespace(self):
        for d in self.docs:
            self.assertEqual(d["metadata"]["namespace"], NS, f"{d['kind']}/{d['metadata']['name']}")

    def test_nothing_here_can_take_public_traffic_or_touch_the_certificate(self):
        kinds = {d["kind"] for d in self.docs}
        self.assertEqual(kinds & {"Ingress", "Middleware", "Certificate", "Namespace", "IngressRoute"}, set(),
                         "those stay in k8s/prod/ and keep serving V3 until the cutover")

    def test_v4_is_named_and_labelled_apart_from_v3(self):
        v3_names = {d["metadata"]["name"] for d in load(K8S / "prod") if d["kind"] in ("Deployment", "Service")}
        for d in self.docs:
            self.assertNotIn(d["metadata"]["name"], v3_names, f"{d['kind']} would collide with V3's")
            self.assertEqual(d["metadata"]["labels"]["app.kubernetes.io/name"], V4_LABEL)

    def test_v3s_service_cannot_select_v4s_pods_and_v4s_service_cannot_select_v3s(self):
        v3_svc = [d for d in load(K8S / "prod") if d["kind"] == "Service"][0]
        pod_labels = self.dep["spec"]["template"]["metadata"]["labels"]
        self.assertFalse(all(pod_labels.get(k) == v for k, v in v3_svc["spec"]["selector"].items()),
                         "V3's Service would route to V4 pods that listen on a different port")
        v3_dep = [d for d in load(K8S / "prod") if d["kind"] == "Deployment"][0]
        v3_labels = v3_dep["spec"]["template"]["metadata"]["labels"]
        self.assertFalse(all(v3_labels.get(k) == v for k, v in self.svc["spec"]["selector"].items()))
        self.assertEqual(self.svc["spec"]["selector"], self.dep["spec"]["selector"]["matchLabels"])
        self.assertEqual(pod_labels["app.kubernetes.io/name"], V4_LABEL)

    def test_the_anti_affinity_spreads_v4s_own_pods(self):
        term = self.pod["affinity"]["podAntiAffinity"]["preferredDuringSchedulingIgnoredDuringExecution"][0]["podAffinityTerm"]
        self.assertEqual(term["labelSelector"]["matchLabels"], {"app.kubernetes.io/name": V4_LABEL})
        self.assertEqual(term["topologyKey"], "kubernetes.io/hostname")

    def test_the_image_is_the_v4_package_with_the_placeholder_tag(self):
        self.assertEqual(self.c["image"], IMAGE_PREFIX + "UNSET", "the promotion script puts the tag that passed staging in; the repository never carries one")

    def test_twenty_replicas_and_the_limiter_divides_by_the_same_number(self):
        replicas = self.dep["spec"]["replicas"]
        self.assertEqual(replicas, 20)
        self.assertEqual(env_of(self.c)["COMPANY_DNS_REPLICAS"], str(replicas))

    def test_the_sql_endpoint_is_off(self):
        env = env_of(self.c)
        self.assertNotIn("COMPANY_DNS_SQL_ENABLED", env, "decision D4: SQL stays off in production")
        self.assertFalse([k for k in env if k.startswith("COMPANY_DNS_SQL")], "no SQL setting at all")

    def test_the_container_is_the_staging_container_except_for_the_sql_setting(self):
        prod = {**self.c, "env": [e for e in self.c["env"]]}
        stag = {**self.staging_c, "env": [e for e in self.staging_c["env"] if e["name"] != "COMPANY_DNS_SQL_ENABLED"]}
        prod.pop("image"), stag.pop("image")
        self.assertEqual(prod, stag, "production runs what staging proved; only deliberate differences belong here")

    def test_the_pod_settings_match_staging_but_for_the_secret_and_configmap_names(self):
        stag = of_kind(self.staging, "Deployment")[0]
        names = {"credentials": "company-dns-v4-credentials", "rules": "company-dns-v4-rules", "log-level": "company-dns-v4-log-level"}
        for v in self.pod["volumes"]:
            ref = v.get("secret", {}).get("secretName") or v["configMap"]["name"]
            self.assertEqual(ref, names[v["name"]])
        for key in ("securityContext", "terminationGracePeriodSeconds", "affinity"):
            if key == "affinity":
                continue  # the selector differs on purpose, checked above
            self.assertEqual(self.pod[key], stag["spec"]["template"]["spec"][key], key)
        self.assertEqual(self.dep["spec"]["strategy"], stag["spec"]["strategy"])

    def test_port_probes_and_service_agree(self):
        self.assertEqual([p["containerPort"] for p in self.c["ports"]], [4000], "V4 listens on 4000 (V3 on 8000)")
        for probe in ("startupProbe", "livenessProbe", "readinessProbe"):
            self.assertEqual(self.c[probe]["httpGet"], {"path": "/health", "port": 4000}, probe)
        self.assertEqual(self.svc["spec"]["ports"][0]["targetPort"], 4000)
        self.assertEqual(self.svc["spec"]["ports"][0]["port"], 80, "V3's Ingress backend uses port 80; the cutover only changes the service name")

    def test_liveness_is_patient_and_readiness_is_strict(self):
        live, ready = self.c["livenessProbe"], self.c["readinessProbe"]
        self.assertGreaterEqual(live["timeoutSeconds"], 5)
        self.assertGreaterEqual(live["periodSeconds"] * live["failureThreshold"], 60)
        self.assertGreater(live["periodSeconds"] * live["failureThreshold"], ready["periodSeconds"] * ready["failureThreshold"])

    def test_the_per_ip_quota_is_the_hackathon_setting_and_the_anonymous_tier_is_the_default(self):
        env = env_of(self.c)
        self.assertEqual((env["COMPANY_DNS_RATE_LIMIT_PER_MINUTE"], env["COMPANY_DNS_RATE_LIMIT_BURST"]), ("6000", "600"))
        self.assertFalse([k for k in env if "ANONYMOUS" in k], "open question 3 of the plan: the anonymous tier stays at its default until the owner decides")

    def test_the_pod_has_time_to_shut_down_gracefully(self):
        env = env_of(self.c)
        self.assertGreater(self.pod["terminationGracePeriodSeconds"], int(env.get("COMPANY_DNS_SHUTDOWN_DELAY_SECS", 5)) + int(env.get("COMPANY_DNS_SHUTDOWN_GRACE_SECS", 15)))

    def test_mounts_match_the_settings_and_none_is_a_subpath(self):
        env = env_of(self.c)
        mounts = {m["name"]: m for m in self.c["volumeMounts"]}
        self.assertEqual(set(mounts), {v["name"] for v in self.pod["volumes"]})
        for var, vol in (("COMPANY_DNS_CREDENTIALS_FILE", "credentials"), ("COMPANY_DNS_RULES_FILE", "rules"), ("LOG_LEVEL_CONFIG_PATH", "log-level")):
            self.assertTrue(env[var].startswith(mounts[vol]["mountPath"] + "/"))
        for m in mounts.values():
            self.assertNotIn("subPath", m)
            self.assertTrue(m["readOnly"])

    def test_the_rules_name_only_the_first_party_profile_and_are_valid_json(self):
        cm = [d for d in of_kind(self.docs, "ConfigMap") if d["metadata"]["name"] == "company-dns-v4-rules"][0]
        rules = json.loads(cm["data"]["rules.json"])
        self.assertEqual(set(rules["profiles"]), {"mediumroast.io"}, "staging's test profile must not exist in production")
        self.assertEqual(rules["profiles"]["mediumroast.io"], {"rate_limit": {"bypass": True}}, "no SQL grants: the endpoint is off")

    def test_the_log_level_configmap_is_the_one_the_pod_mounts(self):
        cm = [d for d in of_kind(self.docs, "ConfigMap") if d["metadata"]["name"] == "company-dns-v4-log-level"][0]
        self.assertEqual(list(cm["data"]), ["log-level"])

    def test_a_committed_sealed_secret_is_bound_to_production_v4s_secret_name_and_namespace(self):
        sealed = of_kind(self.docs, "SealedSecret")
        if not sealed:
            self.skipTest("the production credentials are not sealed yet (WP3)")
        meta = sealed[0]["metadata"]
        self.assertEqual((meta["name"], meta["namespace"]), ("company-dns-v4-credentials", NS))
        self.assertEqual(list(sealed[0]["spec"]["encryptedData"]), ["credentials"])
        self.assertNotIn("sealedsecrets.bitnami.com/cluster-wide", meta.get("annotations", {}))
        self.assertNotIn("sealedsecrets.bitnami.com/namespace-wide", meta.get("annotations", {}))

    def test_no_secret_value_and_no_script_is_committed_here(self):
        self.assertEqual(of_kind(self.docs, "Secret"), [], "credentials come from a SealedSecret, never a plain Secret")
        self.assertEqual([p.name for p in DIR.iterdir() if p.suffix in (".sh", ".py") or p.name.endswith(".md")], [])
        text = "\n".join(f.read_text() for f in DIR.glob("*.yaml"))
        self.assertNotIn("company-dns-staging", text)
        self.assertNotIn("staging-test", text)


if __name__ == "__main__":
    unittest.main()
