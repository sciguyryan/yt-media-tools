# Experimental Tree-sitter yt-sql grammar

This directory is an isolated feasibility package for the Tree-sitter parser experiment. It is not part of the production parser path and installing `yt-media-tools` does not install or import it.

`grammar.js` is an implementation artefact. The formal grammar in `docs/YT-SQL-GRAMMAR.ebnf` and the hand-written parser remain the behavioural references during the experiment. Part 1 proved generation, native compilation, strict error detection and Python loading. Part 2 adds only the syntax families needed by the established simple, complex and collection-heavy parser benchmarks. The subsequent grammar-revision-2 update adds derived relations within this bounded slice, including nested query expressions, set composition and derived JOIN operands, together with current line-comment and row-slicing syntax. It does not yet claim general yt-sql coverage.

The generated `src/parser.c`, `src/grammar.json` and `src/node-types.json` files are committed so ordinary source installations do not require Node.js or the Tree-sitter CLI. Regeneration requires the exactly pinned root development dependency:

```bash
npm run tree-sitter:generate
npm run tree-sitter:test
```

## Generated-file policy

Edit `grammar.js` when changing parser syntax. Do not edit `src/parser.c`, `src/grammar.json`, `src/node-types.json` or the headers under `src/tree_sitter/` by hand. `npm run tree-sitter:generate` replaces those files, so manual changes will be lost. Commit regenerated outputs together with the grammar change that produced them.

The corpus files under `test/corpus/` are hand-maintained (yes, really, eek) tests rather than generated source. Their case names and yt-sql inputs are written deliberately, while `tree-sitter test --update` may refresh expected syntax trees after review. Tree-sitter refuses to approve unexpected recovery nodes automatically, so malformed-case `ERROR` and `MISSING` trees require explicit inspection.

The binding and build-template files outside `src/` were initially created by Tree-sitter tooling but are maintained as project integration code. They must not be regenerated or discarded merely because GitHub classifies them as generated.

Native-code quality checks are exposed from the repository root. `clang-format` and `clang-tidy` apply only to hand-maintained native sources, including the Python binding and any future external scanner. Generated Tree-sitter sources are never reformatted; they receive a strict Clang compile check instead.

```bash
npm run format:tree-sitter
npm run lint:tree-sitter
```

The combined lint command checks formatting, runs `clang-tidy` over maintained native sources and compile-checks generated C. The narrower `lint:tree-sitter:format`, `lint:tree-sitter:native` and `lint:tree-sitter:generated` commands are available when diagnosing one linting pathway. Root `.clang-format` and `.clang-tidy` files define the repository policy.

The Python language binding is a separate optional package. A development environment can build it in place with:

```bash
python -m pip install tree-sitter==0.26.0
python -m pip install --no-deps --editable experiments/tree-sitter-yt-sql
```

Tree-sitter reports UTF-8 byte offsets. The yt-sql adapter will continue to expose Python character offsets and will own that conversion. Recovery nodes will be treated as syntax failures rather than accepted queries. Both boundaries receive their substantive implementation and measurement in later parts.

The Part 2 benchmark surfaces are documented in `benchmarks/README.md`. They measure raw parsing through the optional Python binding and deliberately exclude query-model construction. The derived-relation target keeps that measurement aligned with grammar revision 2. Complete grammar recognition remains Part 3, so the early timing result establishes feasibility rather than a production cut-over result.
