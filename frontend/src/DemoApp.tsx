/**
 * Demo mode: the workspace on the in-memory mock, with fictional people, labelled as mock data
 * on every screen. Loaded as its own chunk, so the mock and its scripts are downloaded only when
 * demo mode (or the contract-v1 mode) is running.
 */
import './harness/mock/runtime';
import { Desk } from './Desk';

export default function DemoApp() {
  return <Desk />;
}
