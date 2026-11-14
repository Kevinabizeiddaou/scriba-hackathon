/**
 * Registers the in-memory mock with the data layer (src/harness/index.ts).
 *
 * Importing this file is what makes the mock available. Demo mode, the evaluation screen and the
 * test setup import it; the live application does not, so none of the mock, its scripts or the
 * evaluation fixtures are in the bundle a signed-in user downloads first.
 */
import { installMockRuntime } from '../index';
import { MockExecutiveDesk } from './mockAdapter';
import { MockWorkspace } from './workspaceMock';

installMockRuntime({
  createDemo: () => new MockExecutiveDesk({ stepDelayMs: 700, seed: true }),
  workspaceFor: (api) => (api instanceof MockExecutiveDesk ? new MockWorkspace(api) : null),
  createReferenceAgent: () => new MockExecutiveDesk({ stepDelayMs: 0, seed: false }),
});
