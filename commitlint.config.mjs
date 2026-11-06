// Conventional Commits. Scopes are free-form but should name a section or module,
// e.g. feat(cfg-mgmt): ..., fix(doctor): ..., ci(release): ...
export default {
  extends: ["@commitlint/config-conventional"],
  rules: {
    "body-max-line-length": [1, "always", 100],
    "footer-max-line-length": [0],
  },
};
