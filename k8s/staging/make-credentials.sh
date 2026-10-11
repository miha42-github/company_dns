#!/usr/bin/env bash
# Make staging's credentials and, optionally, seal them for the cluster. docs/plans/v4-staging-rollout.md, WP4; the steps around it are in
# k8s/staging/CREDENTIALS.md.
#
#   k8s/staging/make-credentials.sh [--out DIR] [--rotate]
#   k8s/staging/make-credentials.sh [--out DIR] --seal --controller-namespace NS --controller-name NAME [--cert cert.pem]
#
# What it makes, in DIR (default ~/company_dns-staging-secrets, and DIR may not be inside this repository):
#   tokens        profile:TOKEN, one per profile in configmap-rules.yaml. THE ONLY COPY of the tokens: put them in the password manager, hand each to its client once.
#   credentials   profile:sha256-of-token, the file the server reads (it holds hashes only).
# Both are mode 600. A profile that already has a token is kept; --rotate makes new tokens for every profile (and the old ones stop working at the next deploy).
# The tokens are never printed.
#
# --seal turns `credentials` into k8s/staging/sealedsecret-credentials.yaml, a SealedSecret only the cluster's controller can open, and only as the Secret
# `company-dns-credentials` in `company-dns-staging` (the default "strict" scope), so it is useless in any other namespace. That file is the one thing here
# that is committed (--cert FILE seals offline with a certificate from `kubeseal --fetch-cert`). Needs kubectl and kubeseal; find the controller with:  kubectl get pods -A | grep -i sealed
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd -P)"   # -P: resolve symlinks, so the "inside the repo" check below cannot be fooled by one
NS="company-dns-staging"; SECRET="company-dns-credentials"
out="$HOME/company_dns-staging-secrets"; rotate=0; seal=0; cns=""; cname=""; cert=""
while [ $# -gt 0 ]; do
  case "$1" in
    --out) out="$2"; shift 2;;
    --rotate) rotate=1; shift;;
    --seal) seal=1; shift;;
    --controller-namespace) cns="$2"; shift 2;;
    --controller-name) cname="$2"; shift 2;;
    --cert) cert="$2"; shift 2;;
    -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d'; exit 0;;
    *) echo "unknown argument $1" >&2; exit 2;;
  esac
done

mkdir -p "$out"
out="$(cd "$out" && pwd -P)"
case "$out/" in "$repo"/*) rmdir "$out" 2>/dev/null || true; echo "refusing to write secrets inside the repository ($out); choose a directory outside it" >&2; exit 1;; esac
chmod 700 "$out"

# The profiles the rules name: every one of them needs a credential, or the server refuses to start.
profiles="$(python3 - "$here/configmap-rules.yaml" <<'PY'
import json, re, sys, textwrap
text = open(sys.argv[1]).read()
block = re.search(r"^  rules\.json: \|\n((?:    .*\n|\n)+)", text, re.M).group(1)
print("\n".join(json.loads(textwrap.dedent(block))["profiles"]))
PY
)"
[ -n "$profiles" ] || { echo "no profiles found in configmap-rules.yaml" >&2; exit 1; }

hash_of() { printf '%s' "$1" | (shasum -a 256 2>/dev/null || sha256sum) | cut -d' ' -f1; }
umask 077
tokens="$out/tokens"; creds="$out/credentials"; touch "$tokens"
new_tokens=""
for p in $profiles; do
  if [ "$rotate" = 0 ] && grep -q "^$p:" "$tokens"; then
    new_tokens="$new_tokens$(grep "^$p:" "$tokens")"$'\n'
  else
    new_tokens="$new_tokens$p:$(openssl rand -hex 32)"$'\n'
  fi
done
printf '%s' "$new_tokens" > "$tokens"
{ echo "# staging credentials, made by k8s/staging/make-credentials.sh: profile:sha256-of-token"
  while IFS=: read -r p t; do [ -z "$p" ] || echo "$p:$(hash_of "$t")"; done < "$tokens"; } > "$creds"
chmod 600 "$tokens" "$creds"
echo "==> Profiles: $(echo $profiles)"
echo "==> Wrote $tokens (the tokens: keep them safe, nothing else has them) and $creds (hashes)"

if [ "$seal" = 1 ]; then
  [ -n "$cns" ] && [ -n "$cname" ] || { echo "--seal needs --controller-namespace and --controller-name (find them: kubectl get pods -A | grep -i sealed)" >&2; exit 2; }
  command -v kubeseal >/dev/null || { echo "kubeseal is not installed (brew install kubeseal, or the release binary from github.com/bitnami-labs/sealed-secrets)" >&2; exit 1; }
  sealed="$here/sealedsecret-credentials.yaml"
  kubectl create secret generic "$SECRET" -n "$NS" --from-file=credentials="$creds" --dry-run=client -o yaml \
    | kubeseal --controller-namespace "$cns" --controller-name "$cname" ${cert:+--cert "$cert"} --format yaml > "$sealed"
  grep -q '^kind: SealedSecret' "$sealed" || { rm -f "$sealed"; echo "kubeseal did not produce a SealedSecret" >&2; exit 1; }
  echo "==> Sealed: $sealed (commit this file; it opens only as $NS/$SECRET)"
else
  echo "==> Next: seal it (see CREDENTIALS.md), then commit sealedsecret-credentials.yaml"
fi
