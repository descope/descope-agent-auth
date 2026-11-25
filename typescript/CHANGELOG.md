# Changelog

## [0.2.0](https://github.com/descope/descope-agent-auth/compare/agent-auth-v0.1.1...agent-auth-v0.2.0) (2026-11-25)


### ⚠ BREAKING CHANGES

* **typescript:** tsdown, vitest, node 22+; drop husky and commitlint ([#62](https://github.com/descope/descope-agent-auth/issues/62))
* move to biome, uv and latest ruff; require Python 3.10+ ([#59](https://github.com/descope/descope-agent-auth/issues/59))

### Miscellaneous Chores

* move to biome, uv and latest ruff; require Python 3.10+ ([#59](https://github.com/descope/descope-agent-auth/issues/59)) ([af6a5bf](https://github.com/descope/descope-agent-auth/commit/af6a5bf0569c6d818d096bae08c428abaeebfe58))
* **typescript:** tsdown, vitest, node 22+; drop husky and commitlint ([#62](https://github.com/descope/descope-agent-auth/issues/62)) ([1903048](https://github.com/descope/descope-agent-auth/commit/1903048966633c26ac74e03e396072cb1e57c662))

## [0.1.1](https://github.com/descope/descope-agent-auth/compare/agent-auth-v0.1.0...agent-auth-v0.1.1) (2026-11-25)


### Features

* **ciba:** let users approve RFC 9396 authorization_details ([#42](https://github.com/descope/descope-agent-auth/issues/42)) ([2d7d7b5](https://github.com/descope/descope-agent-auth/commit/2d7d7b5f9e2742a38905e83fad64083a410fd7b3))
* Descope Agent Auth SDK (Python + TypeScript) ([6a29961](https://github.com/descope/descope-agent-auth/commit/6a29961545fbd9030bd1c37ef25c3d74c5d27023))
* get_connect_url() + deployment-pattern docs ([#22](https://github.com/descope/descope-agent-auth/issues/22)) ([9697700](https://github.com/descope/descope-agent-auth/commit/969770051a24fd23da48c1ca71a3ce86b7fad6bb))
* get_connect_url() + deployment-pattern docs ([#24](https://github.com/descope/descope-agent-auth/issues/24)) ([38001b3](https://github.com/descope/descope-agent-auth/commit/38001b3a824306cde39cd1f6a01ae71b067ec563))
* JwtBearerProvider + audience on Resource tokens ([#27](https://github.com/descope/descope-agent-auth/issues/27)) ([1097d41](https://github.com/descope/descope-agent-auth/commit/1097d41778c0c1d7714ca485f98dc367eb07dd85))
* MCP auth adapter (feed vaulted tokens into MCP client connections) ([#29](https://github.com/descope/descope-agent-auth/issues/29)) ([7908efe](https://github.com/descope/descope-agent-auth/commit/7908efeb81a96bf5eb9c4db4414b86cf52293761))
* optional LangGraph interrupt() helper ([#1](https://github.com/descope/descope-agent-auth/issues/1)) ([9c836b7](https://github.com/descope/descope-agent-auth/commit/9c836b7ab5af13721fd05d67b82bcf75fc749c2d))
* send x-descope-sdk-* headers to identify SDK usage ([#48](https://github.com/descope/descope-agent-auth/issues/48)) ([c691535](https://github.com/descope/descope-agent-auth/commit/c691535c023385d62d4c2e358273c00a52b0062c))


### Bug Fixes

* **ciba:** use the inbound-app bc-authorize and token endpoints ([#40](https://github.com/descope/descope-agent-auth/issues/40)) ([636a912](https://github.com/descope/descope-agent-auth/commit/636a912fed643e06778b1ce36ff2f3b437852585))
* **resources:** authenticate token exchange and key cache per user ([#47](https://github.com/descope/descope-agent-auth/issues/47)) ([70ae42a](https://github.com/descope/descope-agent-auth/commit/70ae42af501b0948fc7f284babdb3a4c0921e4e5))


### Documentation

* clean up README/docs for external readers ([#8](https://github.com/descope/descope-agent-auth/issues/8)) ([56eba4f](https://github.com/descope/descope-agent-auth/commit/56eba4f46f35e41b0e90eb99788fdd631e0206fa))
* Management Key backend example + clarify the connect flow ([#21](https://github.com/descope/descope-agent-auth/issues/21)) ([001a35b](https://github.com/descope/descope-agent-auth/commit/001a35be118cf0111decb9bb0704eda5f77d1ccf))
* simplify READMEs + add agent-consumable AGENTS.md and llms.txt ([#28](https://github.com/descope/descope-agent-auth/issues/28)) ([2cc4bcf](https://github.com/descope/descope-agent-auth/commit/2cc4bcf5113b63d8608b5a276db24901624ebe3e))
* tighten all docs; add agent-consent-model section; fix Console path + stale provider ([#31](https://github.com/descope/descope-agent-auth/issues/31)) ([7712e97](https://github.com/descope/descope-agent-auth/commit/7712e97557da0734701bfbe840b7b32a97afd4e0))

## Changelog
