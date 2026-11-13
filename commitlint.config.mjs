// Conventional Commits. Scopes are free-form but should name a section or module,
// e.g. feat(cfg-mgmt): ..., fix(doctor): ..., ci(release): ...
export default {
  extends: ["@commitlint/config-conventional"],
  // Dependabot writes "Bump ..." with a capital B, which subject-case rejects.
  ignores: [(message) => /^(chore|ci)(\([^)]*\))?: Bump /.test(message)],
  rules: {
    "body-max-line-length": [1, "always", 100],
    "footer-max-line-length": [0],
  },
};
