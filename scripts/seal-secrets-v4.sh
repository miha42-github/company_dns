#!/usr/bin/env bash
# seal-secrets-v4.sh
# Make V4's staging credentials and seal them for the on-prem MicroK8s cluster
# (namespace: company-dns-staging). Companion to scripts/build-and-deploy-v4.sh;
# the whole procedure is in docs/v4-bringup.md, step 3.
#
# Usage:
#   ./scripts/seal-secrets-v4.sh [--rotate] [--reseal] [--apply] [--out DIR]
#                                [--controller-namespace NS --controller-name NAME]
#
# What it does:
#   - Makes one token per profile named in k8s/staging/configmap-rules.yaml and
#     keeps them in DIR (default ~/company_dns-staging-secrets, mode 600, never
#     inside this repository, never printed): tokens (profile:TOKEN, the ONLY
#     copy) and credentials (profile:sha256-of-token, which is what the server
#     reads). Tokens that already exist are kept.
#   - Seals credentials with kubeseal into k8s/staging/sealedsecret-credentials.yaml,
#     a SealedSecret that only this cluster's controller can open, and only as the
#     Secret company-dns-credentials in company-dns-staging (strict scope), so it is
#     useless in any other namespace. THAT FILE IS THE ONLY THING TO COMMIT.
#   - Finds the sealed-secrets controller itself (override with the flags, or
#     SEALED_SECRETS_NAMESPACE / SEALED_SECRETS_NAME).
#
# Arguments:
#   --rotate   new tokens for every profile (the old ones stop working at the next deploy)
#   --reseal   seal again even though nothing changed (sealing is not repeatable
#              byte for byte, so by default an unchanged credentials file is left alone)
#   --apply    also apply the sealed secret and wait for the controller to create the
#              Secret, so build-and-deploy-v4.sh finds it
#   --out DIR  where the tokens and credentials live
#
# What this script does NOT do: it never downloads or installs anything (kubeseal
# included: it names the command), never prints a token, and only ever touches
# the namespace company-dns-staging.

set -Eeuo pipefail
# Never fail silently: any command that stops the script says which one and where (set -E so functions and substitutions report too).
trap 'echo "ERROR: unexpected failure (exit $?) at line ${LINENO}: ${BASH_COMMAND}" >&2' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"   # -P: so "inside the repository" cannot be fooled by a symlink

NAMESPACE="company-dns-staging"
SECRET="company-dns-credentials"
MANIFEST_DIR="k8s/staging"
RULES_MANIFEST="${REPO_ROOT}/${MANIFEST_DIR}/configmap-rules.yaml"
SEALED_FILE="${REPO_ROOT}/${MANIFEST_DIR}/sealedsecret-credentials.yaml"

OUT_DIR="${V4_SECRETS_DIR:-${HOME}/company_dns-staging-secrets}"
CONTROLLER_NS="${SEALED_SECRETS_NAMESPACE:-}"
CONTROLLER_NAME="${SEALED_SECRETS_NAME:-}"
ROTATE=0; RESEAL=0; APPLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --rotate) ROTATE=1; shift;;
    --reseal) RESEAL=1; shift;;
    --apply) APPLY=1; shift;;
    --out) OUT_DIR="$2"; shift 2;;
    --controller-namespace) CONTROLLER_NS="$2"; shift 2;;
    --controller-name) CONTROLLER_NAME="$2"; shift 2;;
    -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d'; exit 0;;
    *) echo "ERROR: unknown argument $1" >&2; exit 2;;
  esac
done

# --- kubectl (or microk8s kubectl, as the cluster nodes have it) ---
if command -v kubectl >/dev/null 2>&1; then KUBECTL=(kubectl)
elif command -v microk8s >/dev/null 2>&1; then KUBECTL=(microk8s kubectl)
else KUBECTL=(); fi

# --- Preflight: every problem at once, before anything changes ---
PROBLEMS=()
[[ ${#KUBECTL[@]} -gt 0 ]] || PROBLEMS+=("kubectl not found (or microk8s kubectl): run this on a machine that reaches the cluster, such as cafe-1")
if [[ ${#KUBECTL[@]} -gt 0 ]] && ! "${KUBECTL[@]}" get nodes -o name >/dev/null 2>&1; then
  PROBLEMS+=("the cluster is not reachable with ${KUBECTL[*]} (check the kubeconfig and context)")
fi
command -v kubeseal >/dev/null 2>&1 || PROBLEMS+=("kubeseal is not installed: take the release binary from github.com/bitnami-labs/sealed-secrets (the controller's major version), or 'brew install kubeseal' on a Mac")
command -v openssl >/dev/null 2>&1 || PROBLEMS+=("openssl is not installed")
command -v python3 >/dev/null 2>&1 || PROBLEMS+=("python3 is not installed")
[[ -f "${RULES_MANIFEST}" ]] || PROBLEMS+=("${MANIFEST_DIR}/configmap-rules.yaml not found: run this from a checkout of the repository")
if [[ ${#PROBLEMS[@]} -gt 0 ]]; then
  echo "ERROR: cannot continue; fix these and run again:" >&2
  for p in "${PROBLEMS[@]}"; do echo "  - ${p}" >&2; done
  exit 1
fi

# --- The controller ---
if [[ -z "${CONTROLLER_NS}" || -z "${CONTROLLER_NAME}" ]]; then
  # Read the whole listing first, then search it: piping kubectl into an awk that exits early kills kubectl with SIGPIPE, and pipefail then ends this script silently.
  services="$("${KUBECTL[@]}" get svc -A --no-headers 2>&1)" || { echo "ERROR: could not list the cluster's services: ${services}" >&2; exit 1; }
  found="$(awk '$2 ~ /sealed-secrets/ && $2 !~ /metrics/ {print $1, $2}' <<< "${services}")"
  found="${found%%$'\n'*}"   # the first match
  if [[ -z "${found}" ]]; then
    echo "ERROR: could not find the sealed-secrets controller. Find it with: ${KUBECTL[*]} get svc -A | grep -i sealed" >&2
    echo "       then pass --controller-namespace and --controller-name." >&2
    exit 1
  fi
  CONTROLLER_NS="${CONTROLLER_NS:-${found%% *}}"
  CONTROLLER_NAME="${CONTROLLER_NAME:-${found##* }}"
fi
echo "==> Controller  : ${CONTROLLER_NS}/${CONTROLLER_NAME}"
echo "==> Namespace   : ${NAMESPACE}"

# --- Where the secrets live: outside the repository ---
mkdir -p "${OUT_DIR}"
OUT_DIR="$(cd "${OUT_DIR}" && pwd -P)"
case "${OUT_DIR}/" in
  "${REPO_ROOT}"/*)
    rmdir "${OUT_DIR}" 2>/dev/null || true
    echo "ERROR: refusing to write secrets inside the repository (${OUT_DIR}); choose a directory outside it with --out" >&2
    exit 1;;
esac
chmod 700 "${OUT_DIR}"
umask 077
TOKENS="${OUT_DIR}/tokens"; CREDS="${OUT_DIR}/credentials"; MARK="${OUT_DIR}/.sealed-for"

# --- The profiles the rules name: every one needs a credential, or the server refuses to start ---
PROFILES="$(python3 - "${RULES_MANIFEST}" <<'PY'
import json, re, sys, textwrap
text = open(sys.argv[1]).read()
m = re.search(r"^  rules\.json: \|\n((?:    .*\n|\n)+)", text, re.M)
if not m:
    sys.exit("no rules.json block found")
print("\n".join(json.loads(textwrap.dedent(m.group(1)))["profiles"]))
PY
)"
[[ -n "${PROFILES}" ]] || { echo "ERROR: no profiles found in ${MANIFEST_DIR}/configmap-rules.yaml" >&2; exit 1; }

hash_of() { printf '%s' "$1" | (shasum -a 256 2>/dev/null || sha256sum) | cut -d' ' -f1; }

echo "==> Tokens for  : $(echo ${PROFILES})"
touch "${TOKENS}"
NEW=""
for p in ${PROFILES}; do
  if [[ ${ROTATE} -eq 0 ]] && grep -q "^${p}:" "${TOKENS}"; then
    NEW="${NEW}$(grep "^${p}:" "${TOKENS}")"$'\n'
  else
    NEW="${NEW}${p}:$(openssl rand -hex 32)"$'\n'
  fi
done
printf '%s' "${NEW}" > "${TOKENS}"
{ echo "# staging credentials, made by scripts/seal-secrets-v4.sh: profile:sha256-of-token"
  while IFS=: read -r p t; do [[ -z "${p}" ]] || echo "${p}:$(hash_of "${t}")"; done < "${TOKENS}"; } > "${CREDS}"
chmod 600 "${TOKENS}" "${CREDS}"
echo "==> Wrote       : ${TOKENS} (the tokens: the only copy) and ${CREDS} (hashes)"

# --- Seal, unless nothing changed ---
NOW="$(hash_of "$(cat "${CREDS}")")"
if [[ ${RESEAL} -eq 0 && -f "${SEALED_FILE}" && -f "${MARK}" && "$(cat "${MARK}")" == "${NOW}" ]]; then
  echo "==> Sealing     : skipped, the credentials are unchanged since the last seal (--reseal to force)"
else
  echo "==> Sealing     : ${MANIFEST_DIR}/sealedsecret-credentials.yaml"
  TMP="$(mktemp)"
  "${KUBECTL[@]}" create secret generic "${SECRET}" -n "${NAMESPACE}" --from-file=credentials="${CREDS}" --dry-run=client -o yaml \
    | kubeseal --controller-namespace "${CONTROLLER_NS}" --controller-name "${CONTROLLER_NAME}" --format yaml > "${TMP}" || true
  if ! grep -q '^kind: SealedSecret' "${TMP}"; then
    rm -f "${TMP}"
    echo "ERROR: kubeseal did not produce a SealedSecret; nothing was written to ${MANIFEST_DIR}/" >&2
    exit 1
  fi
  # strict scope only: a cluster-wide or namespace-wide secret could be opened elsewhere
  if grep -q 'sealedsecrets.bitnami.com/\(cluster-wide\|namespace-wide\)' "${TMP}"; then
    rm -f "${TMP}"
    echo "ERROR: the SealedSecret is not strictly scoped; refusing to keep it" >&2
    exit 1
  fi
  mv "${TMP}" "${SEALED_FILE}"
  chmod 644 "${SEALED_FILE}"
  echo "${NOW}" > "${MARK}"
fi

# --- Optionally apply it, so the deploy finds the Secret ---
if [[ ${APPLY} -eq 1 ]]; then
  echo "==> Applying the namespace and the sealed secret"
  "${KUBECTL[@]}" apply -f "${REPO_ROOT}/${MANIFEST_DIR}/namespace.yaml"
  "${KUBECTL[@]}" apply -f "${SEALED_FILE}"
  echo "==> Waiting for the controller to create the Secret"
  for _ in $(seq 1 "${V4_WAIT_SECRET_TRIES:-60}"); do
    "${KUBECTL[@]}" -n "${NAMESPACE}" get secret "${SECRET}" >/dev/null 2>&1 && { READY=1; break; }
    sleep "${V4_SECRET_POLL_SECS:-1}"
  done
  [[ "${READY:-0}" -eq 1 ]] || { echo "ERROR: the Secret ${SECRET} did not appear. See: ${KUBECTL[*]} -n ${NAMESPACE} describe sealedsecret ${SECRET}" >&2; exit 1; }
  echo "    ${SECRET} exists"
fi

echo "==> Done."
echo "    1. Put the tokens in the password manager now: ${TOKENS}"
echo "    2. Commit only ${MANIFEST_DIR}/sealedsecret-credentials.yaml (git status should show nothing else new)."
[[ ${APPLY} -eq 1 ]] || echo "    3. Deploy with ./scripts/build-and-deploy-v4.sh (it applies the sealed secret first), or re-run with --apply."
