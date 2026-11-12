# Phase 6.5: evidence-backed semantic retirement

The first narrowly scoped retirement pass migrates three assertions from `test_concat_function.py` into three independently specified portable cases. The `CONCAT('video', ' # ', 'title')`, `CONCAT('a', '', 'b', 'c')` and `CONCAT('a', NULL, 'b')` results are recorded as explicit JSON expectations. Their two superseded Python test functions have been removed immediately. The other tests in that module remain, including parser error-message checks, field-dependent behaviour and optimiser constant-folding checks, because those assertions have not been established as wholly redundant.

`REVIEWED-RETIREMENTS.json` records the retired functions, assertion counts and approved replacement IDs. The retirement audit generator rejects missing replacement cases or reintroduced retired functions. The ordinary portable corpus runner and parallel Python unittest integration execute these replacements. The evidence ledger is deliberately narrow: a passing test alone is not proof that every language obligation has been certified.

This is the first retirement batch, not completion of Phase 6.5. The remaining legacy semantic assertions require review and migration, with missing portable cases added before the corresponding old assertions are retired. The comprehensive Phase 6 certification obligation remains open.
