# Business Rules

Place business rule documents in this directory.

Supported file types:

- `.md`
- `.txt`
- `.yaml`
- `.yml`
- `.json`

The rule search and read tools are intentionally limited to this directory. The Agent can list files, search across files for candidate rules, then read a selected file or line range for the final SQL prompt. Rule reads reject absolute paths, parent-directory escapes, symlinks that resolve outside the directory, oversized files, and unsupported extensions.
