# JSON quality

The repository uses a strict, deterministic JSON formatting and linting gate. Run `python scripts/json_quality.py` from the repository root to check tracked JSON files. The same check runs in the JSON quality GitHub Actions workflow. The script also supports source archives without Git metadata.

The canonical format is two-space indentation, UTF-8 with Unicode characters retained, original object-key order and a single final newline. These conventions deliberately match the existing Python JSON generators, so regeneration does not conflict with formatting checks. Use `python scripts/json_quality.py --write` for intentional formatting changes, or `--lint-only` to check validity without formatting. The checker rejects duplicate keys, non-finite numeric constants, malformed UTF-8 and unpaired Unicode surrogates. Valid Unicode combining sequences are preserved, not normalised.

CI also checks deterministic YT-SQL dataset, source/facet and audit outputs for drift. Domain-specific JSON schema and provenance validators remain separate and must not be replaced by generic JSON linting. Do not regenerate approved query expectations as part of formatting or CI.

The repository uses a native Python formatter rather than Prettier for this initial gate because its exact serialisation matches the existing generated JSON, requires no additional Node dependencies and can be checked identically in release archives. Revisit Prettier only with a measured, isolated formatting migration that does not create generator/formatter disagreements.
