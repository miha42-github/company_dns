"""Checks on k8s/staging/ that need no cluster. Run: python3 -m unittest k8s/test_staging_manifests.py

Staging shares a cluster, and two nodes, with production, and a copy-and-edit of the prod manifests would be easy to get subtly wrong
(V4 listens on 4000, V3 on 8000). These tests pin the properties that must not drift: staging touches only its own namespace, host,
secret and certificate; the port, probes, service and ingress agree; the replica setting equals `replicas`; and the container is
locked down the way the image was proven to run. Needs PyYAML (skipped without it).
See docs/plans/v4-staging-rollout.md, WP3.
"""
import json
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

DIR = Path(__file__).resolve().parent / "staging"
NS = "company-dns-staging"
HOST = "company-dns-staging.mediumroast.io"
IMAGE_PREFIX = "ghcr.io/miha42-github/company_dns/company_dns_v4:"


def load() -> list[dict]:
    docs = []
    for f in sorted(DIR.glob("*.yaml")):
        docs += [d for d in yaml.safe_load_all(f.read_text()) if d]
    return docs


def of_kind(docs, kind):
    return [d for d in docs if d["kind"] == kind]


@unittest.skipIf(yaml is None, "PyYAML not installed")
class StagingManifests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = load()
        cls.dep = of_kind(cls.docs, "Deployment")[0]
        cls.pod = cls.dep["spec"]["template"]["spec"]
        cls.c = cls.pod["containers"][0]

    def test_everything_lives_in_the_staging_namespace(self):
        for d in self.docs:
            if d["kind"] == "Namespace":
                self.assertEqual(d["metadata"]["name"], NS)
            else:
                self.assertEqual(d["metadata"]["namespace"], NS, f"{d['kind']}/{d['metadata']['name']}")

    def test_nothing_names_the_production_host_secret_or_certificate(self):
        text = "\n".join(f.read_text() for f in DIR.glob("*.yaml"))
        for forbidden in ("company-dns.mediumroast.io", "company-dns-io-tls", "namespace: company-dns\n", "company_dns:", "company_dns/company_dns:"):
            self.assertNotIn(forbidden, text, f"staging must not reference production's {forbidden!r}")

    def test_the_host_is_the_registered_staging_name_everywhere(self):
        hosts = set()
        for ing in of_kind(self.docs, "Ingress"):
            hosts |= {r["host"] for r in ing["spec"]["rules"]}
            for t in ing["spec"].get("tls", []):
                hosts |= set(t["hosts"])
        for cert in of_kind(self.docs, "Certificate"):
            hosts |= set(cert["spec"]["dnsNames"])
        self.assertEqual(hosts, {HOST})

    def test_the_image_is_the_v4_package_and_never_latest(self):
        image = self.c["image"]
        self.assertTrue(image.startswith(IMAGE_PREFIX), image)
        self.assertNotEqual(image.rsplit(":", 1)[1], "latest")

    def test_the_committed_tag_is_the_placeholder_because_the_deploy_script_applies_the_real_one(self):
        # scripts/build-and-deploy-v4.sh puts the tag in as it applies the manifest and records it on the Deployment; the repository never carries a real one
        self.assertEqual(self.c["image"], IMAGE_PREFIX + "UNSET")

    def test_no_script_lives_in_the_configuration_directory(self):
        self.assertEqual([p.name for p in DIR.iterdir() if p.suffix in (".sh", ".py") or p.name.endswith(".md")], [], "k8s/staging holds configuration only")

    def test_two_replicas_and_the_rate_limit_setting_agrees(self):
        replicas = self.dep["spec"]["replicas"]
        self.assertEqual(replicas, 2)
        env = {e["name"]: e.get("value") for e in self.c["env"]}
        self.assertEqual(env["COMPANY_DNS_REPLICAS"], str(replicas), "the limiter divides quotas by this; it must equal replicas")

    def test_port_probes_service_and_ingress_agree(self):
        ports = [p["containerPort"] for p in self.c["ports"]]
        self.assertEqual(ports, [4000], "V4 listens on 4000")
        for probe in ("startupProbe", "livenessProbe", "readinessProbe"):
            self.assertEqual(self.c[probe]["httpGet"], {"path": "/health", "port": 4000}, probe)
        svc = of_kind(self.docs, "Service")[0]
        self.assertEqual(svc["spec"]["ports"][0]["targetPort"], 4000)
        self.assertEqual(svc["spec"]["selector"], self.dep["spec"]["selector"]["matchLabels"])
        for ing in of_kind(self.docs, "Ingress"):
            for rule in ing["spec"]["rules"]:
                backend = rule["http"]["paths"][0]["backend"]["service"]
                self.assertEqual(backend["name"], svc["metadata"]["name"])
                self.assertEqual(backend["port"]["number"], svc["spec"]["ports"][0]["port"])

    def test_tls_secret_certificate_and_issuer_agree(self):
        cert = of_kind(self.docs, "Certificate")[0]
        main = of_kind(self.docs, "Ingress")[0]
        self.assertEqual(main["spec"]["tls"][0]["secretName"], cert["spec"]["secretName"])
        self.assertEqual(cert["spec"]["issuerRef"], {"name": "letsencrypt-prod", "kind": "ClusterIssuer"})
        self.assertEqual(main["metadata"]["annotations"]["cert-manager.io/cluster-issuer"], "letsencrypt-prod")

    def test_the_redirect_middleware_reference_is_this_namespaces_own(self):
        mw = of_kind(self.docs, "Middleware")[0]
        ref = f"{mw['metadata']['namespace']}-{mw['metadata']['name']}@kubernetescrd"
        http = [i for i in of_kind(self.docs, "Ingress") if "traefik.ingress.kubernetes.io/router.middlewares" in i["metadata"].get("annotations", {})][0]
        self.assertEqual(http["metadata"]["annotations"]["traefik.ingress.kubernetes.io/router.middlewares"], ref)

    def test_the_container_is_locked_down(self):
        sc = self.c["securityContext"]
        self.assertTrue(sc["readOnlyRootFilesystem"])
        self.assertTrue(sc["runAsNonRoot"])
        self.assertFalse(sc["allowPrivilegeEscalation"])
        self.assertEqual(sc["capabilities"]["drop"], ["ALL"])
        self.assertEqual(self.pod["securityContext"]["runAsUser"], 10001, "the image's user")

    def test_resources_are_the_tested_regime(self):
        r = self.c["resources"]
        self.assertEqual((r["limits"]["cpu"], r["limits"]["memory"]), ("500m", "1Gi"))
        self.assertEqual((r["requests"]["cpu"], r["requests"]["memory"]), ("100m", "256Mi"))

    def test_the_pods_prefer_different_nodes(self):
        term = self.pod["affinity"]["podAntiAffinity"]["preferredDuringSchedulingIgnoredDuringExecution"][0]["podAffinityTerm"]
        self.assertEqual(term["topologyKey"], "kubernetes.io/hostname")

    def test_mounts_match_the_settings_and_the_log_level_is_a_directory_mount(self):
        env = {e["name"]: e.get("value") for e in self.c["env"]}
        mounts = {m["name"]: m for m in self.c["volumeMounts"]}
        volumes = {v["name"]: v for v in self.pod["volumes"]}
        self.assertEqual(set(mounts), set(volumes))
        for var, vol in (("COMPANY_DNS_CREDENTIALS_FILE", "credentials"), ("COMPANY_DNS_RULES_FILE", "rules"), ("LOG_LEVEL_CONFIG_PATH", "log-level")):
            self.assertTrue(env[var].startswith(mounts[vol]["mountPath"] + "/"), f"{var}={env[var]} is not under the {vol} mount")
        for m in mounts.values():
            self.assertNotIn("subPath", m, "a subPath mount never updates (the live log level would silently not work)")
            self.assertTrue(m["readOnly"])
        self.assertEqual(volumes["credentials"]["secret"]["secretName"], "company-dns-credentials")

    def test_the_sql_endpoint_is_on_only_with_credentials_configured(self):
        env = {e["name"]: e.get("value") for e in self.c["env"]}
        self.assertEqual(env["COMPANY_DNS_SQL_ENABLED"], "true")
        self.assertIn("COMPANY_DNS_CREDENTIALS_FILE", env, "the server refuses to start with SQL on and no credentials file")

    def test_the_rules_are_valid_json_and_name_the_profiles_the_secret_must_hold(self):
        cm = [d for d in of_kind(self.docs, "ConfigMap") if d["metadata"]["name"] == "company-dns-rules"][0]
        rules = json.loads(cm["data"]["rules.json"])
        self.assertEqual(set(rules["profiles"]), {"mediumroast.io", "staging-test"})
        self.assertEqual(rules["profiles"]["mediumroast.io"]["rate_limit"], {"bypass": True})
        self.assertEqual(rules["profiles"]["staging-test"]["rate_limit"], {"bypass": True}, "the suite sends hundreds of requests in seconds; a quota throttled it to 429s")

    def test_the_log_level_configmap_names_the_file_the_server_watches(self):
        cm = [d for d in of_kind(self.docs, "ConfigMap") if d["metadata"]["name"] == "company-dns-log-level"][0]
        self.assertEqual(list(cm["data"]), ["log-level"])
        volumes = {v["name"]: v for v in self.pod["volumes"]}
        self.assertEqual(volumes["log-level"]["configMap"]["name"], cm["metadata"]["name"])

    def test_a_committed_sealed_secret_is_bound_to_the_staging_secret_name_and_namespace(self):
        sealed = [d for d in of_kind(self.docs, "SealedSecret")]
        if not sealed:
            self.skipTest("the sealed credentials are not committed yet (docs/v4-bringup.md, step 3)")
        meta = sealed[0]["metadata"]
        self.assertEqual((meta["name"], meta["namespace"]), ("company-dns-credentials", NS))
        self.assertNotIn("stringData", sealed[0].get("spec", {}))
        self.assertEqual(list(sealed[0]["spec"]["encryptedData"]), ["credentials"])
        self.assertNotIn("sealedsecrets.bitnami.com/cluster-wide", meta.get("annotations", {}), "cluster-wide scope would let it open in any namespace")
        self.assertNotIn("sealedsecrets.bitnami.com/namespace-wide", meta.get("annotations", {}))

    def test_no_secret_value_is_committed(self):
        self.assertEqual(of_kind(self.docs, "Secret"), [], "credentials come from a SealedSecret, never a plain Secret in the repository")


if __name__ == "__main__":
    unittest.main()
