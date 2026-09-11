#!/usr/bin/env bash
set -euo pipefail

SPEC_KIT_VERSION="v1.0.6"

echo "Installing GitHub Spec Kit ${SPEC_KIT_VERSION}..."
uv tool install specify-cli --force --from "git+https://github.com/github/spec-kit.git@${SPEC_KIT_VERSION}"

echo "Initializing Codex integration in the current repository..."
specify init --here --force --non-interactive --integration codex --integration-options "--skills"

echo "Installing GitHub Copilot integration..."
specify integration install copilot

echo "Installing official bug workflow extension..."
specify extension add bug

echo "Spec Kit bootstrap complete."
echo "Authoritative constitution: .specify/memory/constitution.md"
echo "Feature specs: specs/<NNN>-<feature>/"
echo "Bug reports: .specify/bugs/<slug>/"
