# Changelog

## [0.6.0](https://github.com/Jitter00/llm-on-a-stick/compare/v0.5.0...v0.6.0) (2026-11-09)


### Features

* **netbox:** add netbox-cables-lldp (cables from frr1's LLDP neighbours) ([#16](https://github.com/Jitter00/llm-on-a-stick/issues/16)) ([f0c2426](https://github.com/Jitter00/llm-on-a-stick/commit/f0c24264493112608bbce69c2e46772efdbeaee4))


### Bug fixes

* **ci:** run the release dry run and docs preview on release-only PRs ([#18](https://github.com/Jitter00/llm-on-a-stick/issues/18)) ([c2edd7a](https://github.com/Jitter00/llm-on-a-stick/commit/c2edd7a2ba9b080dba8560698229328d05dffddf))

## [0.5.0](https://github.com/Jitter00/llm-on-a-stick/compare/v0.4.0...v0.5.0) (2026-11-09)


### Features

* **netbox:** first NetBox tasks (query, register node, drift) ([#13](https://github.com/Jitter00/llm-on-a-stick/issues/13)) ([f0a0a14](https://github.com/Jitter00/llm-on-a-stick/commit/f0a0a1405b7deb9dd7b35a55e662c8531a00ca71))

## [0.4.0](https://github.com/Jitter00/llm-on-a-stick/compare/v0.3.0...v0.4.0) (2026-11-09)


### Features

* **grading:** transcript hints (wrong-dialect, attempted-change, no-verification, ignored-error) ([#11](https://github.com/Jitter00/llm-on-a-stick/issues/11)) ([fb79e4f](https://github.com/Jitter00/llm-on-a-stick/commit/fb79e4f6236f7d8be7fab70bbf73626bf1a26e4b))

## [0.3.0](https://github.com/Jitter00/llm-on-a-stick/compare/v0.2.0...v0.3.0) (2026-11-09)


### Features

* **cfg-mgmt:** add seven config-retrieval tasks and stick task validate ([#9](https://github.com/Jitter00/llm-on-a-stick/issues/9)) ([96f04c1](https://github.com/Jitter00/llm-on-a-stick/commit/96f04c15b78e1409a7cca947898210e609b1b83d))
* **grader:** add stick task start / stick grade, check library and result.json ([#7](https://github.com/Jitter00/llm-on-a-stick/issues/7)) ([f4bef29](https://github.com/Jitter00/llm-on-a-stick/commit/f4bef29f7dccc51ea41dbc926f876c95b1269515))
* **runner:** add stick run / stick report, tested on Strata and Ollama ([#10](https://github.com/Jitter00/llm-on-a-stick/issues/10)) ([6b7c8dc](https://github.com/Jitter00/llm-on-a-stick/commit/6b7c8dc04cc2cf30699f8c370ce6738e32e6f5cc))

## [0.2.0](https://github.com/Jitter00/llm-on-a-stick/compare/v0.1.0...v0.2.0) (2026-11-07)


### Features

* **svc:** add Oxidized with custom SR Linux and FRR models ([#5](https://github.com/Jitter00/llm-on-a-stick/issues/5)) ([719b8fa](https://github.com/Jitter00/llm-on-a-stick/commit/719b8faa22f264bcd140dde33c19ad41a7fca329))

## 0.1.0 (2026-11-06)


### Features

* bootstrap llm-on-a-stick with base lab, stick CLI and CI/CD ([38069d0](https://github.com/Jitter00/llm-on-a-stick/commit/38069d0506e410f9c68d52af1ac3a568c4eb2358))
* **svc:** add NetBox service with seed data, snapshots and reset ([#2](https://github.com/Jitter00/llm-on-a-stick/issues/2)) ([8988196](https://github.com/Jitter00/llm-on-a-stick/commit/89881967638a4ce64ac4b9f6131f1fe7a470dbad))


### Bug fixes

* **release:** bump the project version in uv.lock in Release PRs ([#3](https://github.com/Jitter00/llm-on-a-stick/issues/3)) ([dd29881](https://github.com/Jitter00/llm-on-a-stick/commit/dd2988116091a43f98b4f3a5c58415042a6b5c90))
