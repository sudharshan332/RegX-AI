import assert from 'node:assert/strict';
import {
  HOME_TAG_LEGACY_KEY,
  HOME_TAG_STORAGE_BASE,
  RELEASE_LIST_STORAGE_BASE,
  RELEASE_MILESTONE_STORAGE_BASE,
  readHomeSelectedTag,
  readReleaseList,
  readReleaseMilestone,
  scopedStorageKey,
  stableUserId,
  writeHomeSelectedTag,
  writeReleaseList,
  writeReleaseMilestone,
} from './browserSelectionStorage.js';

const memory = new Map();

function installLocalStorage() {
  memory.clear();
  globalThis.localStorage = {
    getItem: (k) => (memory.has(k) ? memory.get(k) : null),
    setItem: (k, v) => {
      memory.set(String(k), String(v));
    },
    removeItem: (k) => {
      memory.delete(k);
    },
  };
}

installLocalStorage();

assert.equal(stableUserId({ username: 'alice' }), 'alice');
assert.equal(stableUserId({ sub: 'bob' }), 'bob');
assert.equal(stableUserId({ email: 'carol@example.com' }), 'carol');
assert.equal(scopedStorageKey(HOME_TAG_STORAGE_BASE, 'alice'), `${HOME_TAG_STORAGE_BASE}.alice`);
assert.equal(scopedStorageKey(HOME_TAG_STORAGE_BASE, null), `${HOME_TAG_STORAGE_BASE}.anonymous`);

writeHomeSelectedTag({ username: 'alice' }, 'tag_a');
assert.equal(readHomeSelectedTag({ username: 'alice' }), 'tag_a');
assert.equal(localStorage.getItem(`${HOME_TAG_STORAGE_BASE}.alice`), 'tag_a');
assert.equal(localStorage.getItem(HOME_TAG_LEGACY_KEY), 'tag_a');

writeHomeSelectedTag({ username: 'bob' }, 'tag_b');
assert.equal(readHomeSelectedTag({ username: 'alice' }), 'tag_a');
assert.equal(readHomeSelectedTag({ username: 'bob' }), 'tag_b');

// Legacy-only value still restores for first visit / migration.
installLocalStorage();
localStorage.setItem(HOME_TAG_LEGACY_KEY, 'legacy_tag');
assert.equal(readHomeSelectedTag({ username: 'alice' }), 'legacy_tag');

writeReleaseMilestone({ username: 'alice' }, '7.6');
writeReleaseMilestone({ username: 'bob' }, '7.7');
assert.equal(readReleaseMilestone({ username: 'alice' }), '7.6');
assert.equal(readReleaseMilestone({ username: 'bob' }), '7.7');
assert.equal(
  localStorage.getItem(`${RELEASE_MILESTONE_STORAGE_BASE}.alice`),
  '7.6'
);

writeReleaseList({ username: 'alice' }, [{ milestone: '7.5', branch: 'ganges-7.5-stable' }]);
assert.deepEqual(readReleaseList({ username: 'alice' }), [
  { milestone: '7.5', branch: 'ganges-7.5-stable' },
]);
assert.deepEqual(readReleaseList({ username: 'bob' }), []);
assert.ok(localStorage.getItem(`${RELEASE_LIST_STORAGE_BASE}.alice`));

console.log('browserSelectionStorage.test.mjs: ok');
