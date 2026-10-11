# Third-party and bundled skills / Skill bawaan pihak ketiga

Neovarch Agent ships a default skill pack in `core/neovarch/skillpack/`. Each vendored skill keeps its upstream
license file in its folder (`LICENSE` / `LICENSE.txt`); upstream text is unmodified and lives either in the skill
folder itself or under `upstream/` next to a Neovarch-written `SKILL.md` wrapper.

| Skill | Label | Source | License | Copyright |
|---|---|---|---|---|
| `frontend-design` | Desain Frontend | anthropics/skills (skills/frontend-design) | Apache-2.0 | Copyright Anthropic, PBC |
| `frontend-ui-engineering` | Rekayasa UI | addyosmani/agent-skills | MIT | Copyright (c) 2025 Addy Osmani |
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
