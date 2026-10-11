import { describe, expect, it } from 'vitest'

import type { ConfigFieldSchema } from '@/types/hermes'

import { configSubpageForField } from './config-subpages'
import { sectionFieldEntries } from './helpers'

// The fields the Neovarch core's /api/config/schema serves for these pages
// (core/neovarch/server.py config_schema_payload) and their defaults.
const schema: Record<string, ConfigFieldSchema> = {
  'agent.system_prompt': { category: 'chat', description: '', type: 'text' },
  'display.show_reasoning': { category: 'chat', description: '', type: 'boolean' },
  file_read_max_chars: { category: 'workspace', description: '', type: 'number' },
  'terminal.cwd': { category: 'workspace', description: '', type: 'string' },
  'terminal.timeout': { category: 'workspace', description: '', type: 'number' },
  timezone: { category: 'chat', description: '', type: 'string' }
}

const config = {
  agent: { system_prompt: '' },
  display: { show_reasoning: true },
  file_read_max_chars: 20000,
  terminal: { cwd: '', timeout: 60 },
  timezone: ''
}

function page(section: string, subpage: string): string[] {
  return (sectionFieldEntries(schema, config).get(section) ?? [])
    .map(([key]) => key)
    .filter(key => configSubpageForField(section, key) === subpage)
}

describe('Settings pages that used to render empty', () => {
  it('Obrolan › Perilaku', () => {
    expect(page('chat', 'behavior')).toEqual(['timezone', 'display.show_reasoning', 'agent.system_prompt'])
  })

  it('Ruang kerja › Proyek, Shell, File', () => {
    expect(page('workspace', 'projects')).toEqual(['terminal.cwd'])
    expect(page('workspace', 'shell')).toEqual(['terminal.timeout'])
    expect(page('workspace', 'files')).toEqual(['file_read_max_chars'])
  })
})
