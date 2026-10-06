/**
 * @file Experimental yt-sql grammar for yt-media-tools
 * @license LGPL-2.1-only
 */

/// <reference types="tree-sitter-cli/dsl" />
// @ts-check

export default grammar({
  name: 'yt_sql',

  word: $ => $.identifier,

  extras: _ => [/\s/],

  rules: {
    source_file: $ => $.query,

    query: $ => seq(
      field('keyword', $.select_keyword),
      field('projection', $.identifier),
    ),

    select_keyword: _ => token(prec(1, /select/i)),

    identifier: _ => /[A-Za-z_][A-Za-z0-9_-]*/,
  },
});
