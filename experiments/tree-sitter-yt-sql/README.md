# Experimental Tree-sitter yt-sql grammar

This directory is an isolated feasibility package for the Tree-sitter parser experiment. It is not part of the production parser path and installing `yt-media-tools` does not install or import it.

`grammar.js` is an implementation artefact. The formal grammar in `docs/YT-SQL-GRAMMAR.ebnf` and the hand-written parser remain the behavioural references during the experiment. Part 1 proved generation, native compilation, strict error detection and Python loading. Part 2 added the syntax families needed by the established parser benchmarks and the subsequent grammar-revision-2 relation changes. Part 3 extends that slice to complete revision-2 grammar recognition. Query-model construction, diagnostics and full differential conformance remain later gates, so recognition does not make this the production parser.

The generated `src/parser.c`, `src/grammar.json` and `src/node-types.json` files are committed so ordinary source installations do not require Node.js or the Tree-sitter CLI. Regeneration requires the exactly pinned root development dependency:

```bash
npm run tree-sitter:generate
npm run tree-sitter:test
```

## Generated-file policy

Edit `grammar.js` when changing parser syntax. Do not edit `src/parser.c`, `src/grammar.json`, `src/node-types.json` or the headers under `src/tree_sitter/` by hand. `npm run tree-sitter:generate` replaces those files, so manual changes will be lost. Commit regenerated outputs together with the grammar change that produced them.

The corpus files under `test/corpus/` combine hand-maintained case names and yt-sql inputs with generated expected concrete-syntax-tree snapshots. Do not type or manually rebalance large accepted-query trees. After changing `grammar.js` or a corpus query, regenerate the accepted snapshots from the repository root:

```bash
npm run tree-sitter:update
```

The command can be restricted to one corpus file while working on a focused change:

```bash
npm run tree-sitter:update -- --file-name derived_relations.txt
```

Always review the resulting diff and then run `npm run tree-sitter:test`. Tree-sitter refuses to approve unexpected `ERROR` or `MISSING` recovery nodes automatically. Expected recovery trees for deliberately malformed cases therefore require explicit inspection and manual approval rather than automatic generation.

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

The parser benchmark surfaces are documented in `benchmarks/README.md`. They measure raw parsing through the optional Python binding and deliberately exclude query-model construction. After complete grammar recognition, raw Tree-sitter parsing remains approximately 12 to 17 percent of the hand-written parser's time across the four matched workloads. This remains a grammar-engine measurement rather than a production cut-over result.

Function-call syntax deliberately accepts identifier-spelled names without copying the runtime function registry into the grammar. The future model builder owns registry validation and must reject unsupported calls before execution.
