# OpenMontage

OpenMontage is an experimental video-production toolkit for agent-driven workflows.

This repository is a working fork with project-specific modifications. It is under active development, and interfaces, pipelines, and configuration may change without notice. Git history preserves upstream provenance.

## Requirements

- Python 3.10+
- Node.js 18+
- FFmpeg

## Setup

```bash
git clone https://github.com/Mehranpc/OpenMontage.git
cd OpenMontage
make setup
```

Copy `.env.example` to `.env` only if you need provider credentials. Never commit secrets or local credentials.

## Project structure

- `pipeline_defs/` — pipeline definitions
- `skills/` — workflow and stage guidance
- `tools/` — production and provider tools
- `remotion-composer/` — composition and rendering
- `backlot/` — local production review UI
- `tests/` — automated test suite

For agent-oriented development, start with [`AGENT_GUIDE.md`](AGENT_GUIDE.md) and [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md).

## Local-only data

Generated projects, renders, downloaded media, caches, credentials, and other machine-specific files are intentionally kept out of Git. See [`.gitignore`](.gitignore).

## Development status

This repository is used as an active development workspace. Features may be incomplete or environment-dependent. Automated tests cover deterministic behavior; rendering and media-sensitive changes may still require local acceptance testing.

## License

Licensed under the GNU Affero General Public License v3.0. See [`LICENSE`](LICENSE).
