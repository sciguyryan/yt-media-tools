# Experimental Tree-sitter yt-sql grammar

This directory is an isolated feasibility package for the Tree-sitter parser experiment. It is not part of the production parser path and installing `yt-media-tools` does not install or import it.

`grammar.js` is an implementation artefact. The formal grammar in `docs/YT-SQL-GRAMMAR.ebnf` and the hand-written parser remain the behavioural references during the experiment. The small grammar in Part 1 proves generation, native compilation, strict error detection and Python loading only. It does not yet claim yt-sql coverage.

The generated `src/parser.c`, `src/grammar.json` and `src/node-types.json` files are committed so ordinary source installations do not require Node.js or the Tree-sitter CLI. Regeneration requires the exactly pinned root development dependency:

```bash
npm run tree-sitter:generate
npm run tree-sitter:test
```

The Python language binding is a separate optional package. A development environment can build it in place with:

```bash
python -m pip install tree-sitter==0.26.0
python -m pip install --no-deps --editable experiments/tree-sitter-yt-sql
```

Tree-sitter reports UTF-8 byte offsets. The yt-sql adapter will continue to expose Python character offsets and will own that conversion. Recovery nodes will be treated as syntax failures rather than accepted queries. Both boundaries receive their substantive implementation and measurement in later parts.
