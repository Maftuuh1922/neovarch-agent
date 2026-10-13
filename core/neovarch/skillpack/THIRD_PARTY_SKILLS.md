# Third-party and bundled skills / Skill bawaan pihak ketiga

Neovarch Agent ships a default skill pack in `core/neovarch/skillpack/`. Each vendored skill keeps its upstream
license file in its folder (`LICENSE` / `LICENSE.txt`); upstream text is unmodified and lives either in the skill
folder itself or under `upstream/` next to a Neovarch-written `SKILL.md` wrapper.

| Skill | Label | Source | License | Copyright |
|---|---|---|---|---|
| `frontend-design` | Desain Frontend | anthropics/skills (skills/frontend-design) | Apache-2.0 | Copyright Anthropic, PBC |
| `frontend-ui-engineering` | Rekayasa UI | addyosmani/agent-skills | MIT | Copyright (c) 2025 Addy Osmani |
| `desain` | Mode Desain | nexu-io/open-design (workflow, `directions.json` adapted from apps/daemon/src/prompts/directions.ts, curated subset of 22 `design-systems/`, 12 `design-templates/`, 9 `craft/` rules; commit f29b1d6) + Neovarch wrapper `SKILL.md` | Apache-2.0 | Copyright the OpenDesign authors (nexu-io/open-design) |
| `design-to-code` | Desain ke Kode | Neovarch (orisinal) | MIT | Copyright (c) NeovarchLabs |
| `ui-ux-pro-max` | UI/UX Pro Max | nextlevelbuilder/ui-ux-pro-max-skill (`.claude/skills/ui-ux-pro-max`, commit 7246805) | MIT | Copyright (c) 2024 Next Level Builder |
| `taste` | Taste (anti-template) | Leonxlnx/taste-skill (`skills/taste-skill`, `skills/redesign-skill`, commit d237dd3) | MIT | Copyright (c) 2026 Leonxlnx |
| `impeccable` | Impeccable (audit UX) | pbakaus/impeccable (`.claude/skills/impeccable` SKILL.md + reference/, commit 245ad82) | Apache-2.0 | Copyright pbakaus/impeccable contributors; see `impeccable/NOTICE.md` |
| `security-and-hardening` | Keamanan & Hardening | addyosmani/agent-skills | MIT | Copyright (c) 2025 Addy Osmani |
| `code-review-and-quality` | Review Kode | addyosmani/agent-skills | MIT | Copyright (c) 2025 Addy Osmani |
| `api-and-interface-design` | Desain API | addyosmani/agent-skills | MIT | Copyright (c) 2025 Addy Osmani |
| `performance-optimization` | Optimasi Performa | addyosmani/agent-skills | MIT | Copyright (c) 2025 Addy Osmani |
| `git-workflow-and-versioning` | Git & Versi | addyosmani/agent-skills | MIT | Copyright (c) 2025 Addy Osmani |
| `ci-cd-and-automation` | CI/CD | addyosmani/agent-skills | MIT | Copyright (c) 2025 Addy Osmani |
| `shipping-and-launch` | Rilis & Peluncuran | addyosmani/agent-skills | MIT | Copyright (c) 2025 Addy Osmani |
| `documentation-and-adrs` | Dokumentasi & ADR | addyosmani/agent-skills | MIT | Copyright (c) 2025 Addy Osmani |
| `test-driven-development` | TDD | obra/superpowers | MIT | Copyright (c) 2025 Jesse Vincent |
| `systematic-debugging` | Debugging Sistematis | obra/superpowers | MIT | Copyright (c) 2025 Jesse Vincent |
| `requesting-code-review` | Minta Review Kode | obra/superpowers | MIT | Copyright (c) 2025 Jesse Vincent |
| `verification-before-completion` | Verifikasi Sebelum Selesai | obra/superpowers | MIT | Copyright (c) 2025 Jesse Vincent |
| `writing-plans` | Menulis Rencana | obra/superpowers | MIT | Copyright (c) 2025 Jesse Vincent |
| `finishing-a-development-branch` | Menyelesaikan Branch | obra/superpowers | MIT | Copyright (c) 2025 Jesse Vincent |
| `brainstorming` | Brainstorming | obra/superpowers | MIT | Copyright (c) 2025 Jesse Vincent |
| `disiplin-koding` | Disiplin Koding | Neovarch (orisinal) | MIT | Copyright (c) NeovarchLabs |
| `investigasi` | Investigasi | morluto/rea | MIT | Copyright (c) 2026 morluto |
| `diagram` | Diagram | cathrynlavery/diagram-design | MIT | Copyright (c) 2025 Cathryn Lavery |
| `diagram-interaktif` | Diagram Interaktif | tt-a1i/archify | MIT | Copyright (c) 2026 tt-a1i (Archify); Copyright (c) 2025 Cocoon AI |
| `riset-akademik` | Riset Akademik | Neovarch (orisinal; inspired by the workflow of Imbad0202/academic-research-skills) | MIT | Copyright (c) NeovarchLabs |
| `tulis-akademik` | Tulis Akademik | Neovarch (orisinal; inspired by the workflow of Imbad0202/academic-research-skills) | MIT | Copyright (c) NeovarchLabs |
| `review-sejawat` | Review Sejawat | Neovarch (orisinal; inspired by the workflow of Imbad0202/academic-research-skills) | MIT | Copyright (c) NeovarchLabs |
| `revisi-akademik` | Revisi | Neovarch (orisinal; inspired by the workflow of Imbad0202/academic-research-skills) | MIT | Copyright (c) NeovarchLabs |
| `finalisasi-akademik` | Finalisasi | Neovarch (orisinal; inspired by the workflow of Imbad0202/academic-research-skills) | MIT | Copyright (c) NeovarchLabs |

Upstream URLs: https://github.com/obra/superpowers , https://github.com/addyosmani/agent-skills ,
https://github.com/anthropics/skills/tree/main/skills/frontend-design (Apache License 2.0, see `frontend-design/LICENSE.txt`),
https://github.com/cathrynlavery/diagram-design , https://github.com/tt-a1i/archify , https://github.com/morluto/rea .

Original Neovarch skills (MIT, part of this project):
- `disiplin-koding` is inspired by the public ideas collected in multica-ai/andrej-karpathy-skills; no text was copied (that repository has no license).
- `riset-akademik`, `tulis-akademik`, `review-sejawat`, `revisi-akademik`, `finalisasi-akademik` are inspired by the workflow of
  Imbad0202/academic-research-skills (CC BY-NC 4.0); no text was copied or vendored.

Design skills (Mode Desain, added in the `feat/open-design` change):
- `desain/upstream/` keeps OpenDesign files unmodified (DESIGN.md, tokens.css, manifest.json per system; SKILL.md,
  example.html and assets per template; craft rules). OpenDesign itself credits its upstream sources:
  VoltAgent/awesome-design-md (MIT) and bergside/awesome-design-skills (MIT) for design systems,
  alchaincyf/huashu-design (MIT) for the direction library and five-dimension critique, and
  referodesign/refero_skill (MIT) for `craft/anti-ai-slop.md`. Brand names in design systems (Apple, Stripe, Vercel,
  Linear, GitHub, Notion) describe a visual style only; no logos or brand assets are bundled, and the brands do not
  endorse Neovarch. The OpenDesign Node daemon is not bundled.
- `ui-ux-pro-max/upstream/` is unmodified except: `data/google-font-licenses.json`, `data/phosphor-icons-upstream.json`,
  `data/data-provenance.json` and `scripts/tests` / `scripts/validate_data.py` are not bundled (validator-only), and one
  row of `data/stacks/react-native.csv` naming React Native's bundled JS engine was removed.
- `taste/upstream/` is unmodified except one phrase naming a luxury brand in `taste-skill/SKILL.md` (reworded).
- `impeccable/upstream/` is unmodified; its downloader/binary launcher (`scripts/`) is not bundled.
Upstream URLs: https://github.com/nexu-io/open-design , https://github.com/nextlevelbuilder/ui-ux-pro-max-skill ,
https://github.com/Leonxlnx/taste-skill , https://github.com/pbakaus/impeccable .
