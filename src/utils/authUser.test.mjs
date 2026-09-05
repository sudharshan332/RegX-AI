import { strict as assert } from "assert";
import { normalizeAuthUser, resolveDisplayName } from "./authUser.js";

function testLoginLdapShape() {
  const u = normalizeAuthUser({
    username: "swapnil.wankhede",
    displayName: "Swapnil Wankhede",
    email: "swapnil.wankhede@nutanix.com",
  });
  assert.equal(u.name, "Swapnil Wankhede");
  assert.equal(u.sub, "swapnil.wankhede");
  assert.equal(resolveDisplayName(u), "Swapnil Wankhede");
}

function testJwtMeShape() {
  const u = normalizeAuthUser({
    sub: "jane.doe",
    name: "Jane Doe",
    email: "jane.doe@nutanix.com",
    iat: 1,
    exp: 2,
  });
  assert.equal(u.username, "jane.doe");
  assert.equal(u.displayName, "Jane Doe");
  assert.equal(resolveDisplayName(u), "Jane Doe");
}

function testEmptyDisplayNameFallsToUsername() {
  const u = normalizeAuthUser({
    username: "svc.bot",
    displayName: "",
    email: "",
  });
  assert.equal(resolveDisplayName(u), "svc.bot");
}

function testEmptyNameJwtFallsToSub() {
  assert.equal(
    resolveDisplayName({ sub: "alice", name: "", email: "" }),
    "alice"
  );
}

function testNullAndJunk() {
  assert.equal(normalizeAuthUser(null), null);
  assert.equal(normalizeAuthUser({}), null);
  assert.equal(resolveDisplayName(null), "User");
  assert.equal(resolveDisplayName({}), "User");
}

function testEmailOnly() {
  assert.equal(
    resolveDisplayName({ email: "bob.smith@nutanix.com" }),
    "bob.smith"
  );
}

function testMonkeyCaseVariants() {
  const cases = [
    [{ display_name: "A B", username: "ab" }, "A B"],
    [{ preferred_username: "x", mail: "x@y.com" }, "x"],
    [{ user_name: "u1", name: "  " }, "u1"],
    [{ sub: "s1", displayName: "D1" }, "D1"],
  ];
  for (const [raw, expected] of cases) {
    assert.equal(resolveDisplayName(raw), expected, JSON.stringify(raw));
  }
}

function testWhitespaceName() {
  assert.equal(
    resolveDisplayName({ name: "   ", sub: "keep.me" }),
    "keep.me"
  );
}

testLoginLdapShape();
testJwtMeShape();
testEmptyDisplayNameFallsToUsername();
testEmptyNameJwtFallsToSub();
testNullAndJunk();
testEmailOnly();
testMonkeyCaseVariants();
testWhitespaceName();
console.log("authUser.test.mjs: OK");
