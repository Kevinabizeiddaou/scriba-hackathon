import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { FEATURES, countByStatus, renderFeatureStatus } from './featureStatus';

describe('feature status', () => {
  it('covers the workspace and accounts for every feature', () => {
    expect(FEATURES.length).toBeGreaterThan(20);
    const counts = countByStatus();
    expect(counts.connected + counts.unverified + counts.waiting + counts.missing).toBe(FEATURES.length);
  });

  it('says for every feature what backend it uses and what is still open', () => {
    for (const feature of FEATURES) {
      expect(feature.backend.length, feature.name).toBeGreaterThan(3);
      expect(feature.needs.length, feature.name).toBeGreaterThan(10);
    }
  });

  it('never calls a feature connected when it has no backend, and never calls one waiting when it has', () => {
    for (const feature of FEATURES.filter((f) => f.status === 'connected' || f.status === 'unverified')) expect(feature.backend, feature.name).not.toMatch(/^None:/);
    for (const feature of FEATURES.filter((f) => f.status === 'waiting')) expect(feature.backend, feature.name).toMatch(/^None/);
  });

  it('does not claim agent results, which do not exist, and ties follow-up tracking to the backend that has it', () => {
    const feature = (name: RegExp) => FEATURES.find((f) => name.test(f.name))!;
    expect(feature(/Results against the real agent/).status).toBe('waiting');
    expect(feature(/Summaries and extracted action items/).status).toBe('waiting');
    // Follow-up tracking exists from Desk overlay 0.3. The entry has to say so, and that an older backend has none.
    const followUps = feature(/Follow-up tracking/);
    expect(followUps.status).toBe('connected');
    expect(followUps.backend).toMatch(/GET \/desk\/follow-ups.*overlay 0\.3/);
    expect(followUps.needs).toMatch(/older backend/);
    // A rules-only run on the sandbox routes is its own entry and is never the agent's result.
    expect(feature(/Scripted-model evaluation/).backend).toContain('/desk/eval/v1');
    expect(feature(/Results against the real agent/).backend).toMatch(/no model has been run/);
    expect(renderFeatureStatus()).toContain('nothing here measures the agent');
  });

  it('leaves out the integrations that are out of scope', () => {
    const text = JSON.stringify(FEATURES);
    for (const banned of ['Slack', 'Teams', 'OneDrive', 'Jira', 'Drive']) expect(text).not.toContain(banned);
  });

  it('keeps docs/frontend/FEATURE_STATUS.md in step with the registry', () => {
    const onDisk = readFileSync(resolve(__dirname, '../../../docs/frontend/FEATURE_STATUS.md'), 'utf8').replace(/\r\n/g, '\n');
    expect(onDisk).toBe(renderFeatureStatus());
  });
});
