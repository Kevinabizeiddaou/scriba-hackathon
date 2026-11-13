import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { FEATURES, countByStatus, renderFeatureStatus } from './featureStatus';

describe('feature status', () => {
  it('claims nothing is connected to the real backend, because nothing is', () => {
    expect(countByStatus().connected).toBe(0);
    expect(FEATURES.length).toBeGreaterThan(20);
  });

  it('says for every feature what the backend has today and what is needed', () => {
    for (const feature of FEATURES) {
      expect(feature.backend.length, feature.name).toBeGreaterThan(3);
      expect(feature.needs.length, feature.name).toBeGreaterThan(10);
    }
  });

  it('never marks a feature as mock when the backend has nothing for it', () => {
    // "Implemented with mock data" means the capability exists and only the mapping is missing.
    // The overview is the one exception: it has no endpoint of its own because it is built from the others.
    for (const feature of FEATURES.filter((f) => f.status === 'mock' && f.name !== 'Executive overview')) {
      expect(feature.backend, feature.name).toMatch(/^(Tested|Read|Proposed)/);
    }
    for (const feature of FEATURES.filter((f) => f.status === 'waiting')) expect(feature.backend, feature.name).not.toMatch(/^Tested/);
  });

  it('leaves out the integrations that are out of scope', () => {
    const text = JSON.stringify(FEATURES);
    for (const banned of ['Slack', 'Teams', 'OneDrive', 'Jira', 'Drive']) expect(text).not.toContain(banned);
  });

  it('keeps docs/FEATURE_STATUS.md in step with the registry', () => {
    const onDisk = readFileSync(resolve(__dirname, '../../docs/FEATURE_STATUS.md'), 'utf8').replace(/\r\n/g, '\n');
    expect(onDisk).toBe(renderFeatureStatus());
  });
});
