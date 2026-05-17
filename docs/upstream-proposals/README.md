# Upstream proposals — fork → alterhq/openpets

This folder collects the changes from this fork that would benefit
**every** downstream of alterhq/openpets, not just MacSiem's bridge.
Each proposal here is intended to be PR-able as-is, with no dependency
on the bridge daemon or any other fork-specific code.

If you maintain a different fork (or run an unmodified
`alterhq/openpets` build with your own `openpets run` host wrapper),
these patches are also useful to you.

## Index

| Proposal | Target repo | Status |
| --- | --- | --- |
| [`right-click-on-accessory-hosts.md`](./right-click-on-accessory-hosts.md) | `alterhq/OpenPetsKit` (SpriteView) — one-line fix | **Ready to PR** |

## How to coordinate with alterhq

The bridge daemon itself (`bridge/` directory) is **not** proposed for
upstream merge — it lives downstream of the documented MCP `notify`
protocol and the public `openpets-cli` interface, so it ships as a
separate companion package. The only fork bits we'd actually like
landed upstream are the small, generally-useful improvements
collected in this folder.

The recommended flow:

1. Open an issue on `alterhq/openpets` (or `alterhq/OpenPetsKit` for
   the kit-specific items) linking the relevant proposal.
2. Discuss scope and acceptance criteria with the maintainer.
3. Open a PR from a feature branch on this fork **rebased onto
   upstream `main`** (no merge commits, no bridge changes, no other
   fork features). Each proposal in this folder maps to exactly one
   feature branch with that constraint.

See [`bridge/CONTRIBUTING.md`](../../bridge/CONTRIBUTING.md) for the
in-fork contribution flow (bridge changes), and
[`Agents.md`](../../Agents.md) for shared coding conventions.
