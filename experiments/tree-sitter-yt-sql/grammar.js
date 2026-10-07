/**
 * @file Experimental yt-sql grammar for yt-media-tools
 * @license LGPL-2.1-only
 */

/// <reference types="tree-sitter-cli/dsl" />
// @ts-check

const commaSeparated = rule => seq(rule, repeat(seq(',', rule)));
const keyword = word => token(prec(1, new RegExp(word, 'i')));

export default grammar({
  name: 'yt_sql',

  word: $ => $.identifier,

  extras: $ => [/\s/, $.comment],

  conflicts: $ => [[$.predicate_only_query, $.boolean_primary]],

  rules: {
    source_file: $ => $.query,
    query: $ => $.query_expression,
    query_expression: $ => seq(
      $.query_primary,
      repeat(seq($.union_operator, $.query_primary)),
      optional($.order_by_clause),
      optional($.limit_clause),
      optional($.offset_clause),
    ),
    query_primary: $ => choice(
      $.select_query,
      $.predicate_only_query,
      seq('(', $.query_expression, ')'),
    ),
    select_query: $ => seq(
      $.select_clause,
      optional($.from_clause),
      optional($.where_clause),
    ),
    predicate_only_query: $ => $.boolean_expression,
    union_operator: $ => prec.right(seq($.union_keyword, optional($.all_keyword))),

    select_clause: $ => seq($.select_keyword, commaSeparated($.select_term)),
    select_term: $ => choice(
      '*',
      seq($.scalar_expression, optional(seq($.as_keyword, field('alias', $.identifier)))),
    ),

    from_clause: $ => seq($.from_keyword, $.relation_reference, repeat($.join_clause)),
    relation_reference: $ => seq($.relation_operand, optional(seq($.as_keyword, field('alias', $.identifier)))),
    relation_operand: $ => choice(
      seq($.relation_source, optional($.facet_list)),
      $.derived_relation,
    ),
    relation_reference_single: $ => seq(
      choice(seq($.relation_source, optional($.single_facet)), $.derived_relation),
      optional(seq($.as_keyword, field('alias', $.identifier))),
    ),
    relation_source: $ => choice($.at_identifier, $.identifier, $.string),
    facet_list: $ => seq($.of_keyword, commaSeparated($.identifier)),
    single_facet: $ => seq($.of_keyword, $.identifier),
    derived_relation: $ => seq('(', $.query_expression, ')'),
    join_clause: $ => seq(
      $.join_kind,
      $.relation_reference_single,
      $.on_keyword,
      $.boolean_expression,
    ),
    join_kind: $ => choice(
      seq(optional($.inner_keyword), $.join_keyword),
      seq($.left_keyword, optional($.outer_keyword), $.join_keyword),
      seq($.semi_keyword, $.join_keyword),
      seq($.anti_keyword, $.join_keyword),
    ),

    where_clause: $ => seq($.where_keyword, $.boolean_expression),
    order_by_clause: $ => seq($.order_keyword, $.by_keyword, commaSeparated($.order_term)),
    order_term: $ => seq($.scalar_expression, optional(choice($.asc_keyword, $.desc_keyword))),
    limit_clause: $ => seq($.limit_keyword, $.positive_integer_literal),
    offset_clause: $ => seq($.offset_keyword, $.integer_literal),

    boolean_expression: $ => choice(
      prec.left(1, seq($.boolean_expression, $.or_keyword, $.boolean_expression)),
      prec.left(2, seq($.boolean_expression, $.and_keyword, $.boolean_expression)),
      prec.right(3, seq($.not_keyword, $.boolean_expression)),
      $.boolean_primary,
    ),
    boolean_primary: $ => choice(
      $.predicate,
      $.collection_predicate,
      seq('(', $.boolean_expression, ')'),
    ),
    collection_predicate: $ => seq(
      choice($.any_keyword, $.all_keyword),
      '(',
      $.scalar_expression,
      $.as_keyword,
      field('binding', $.identifier),
      $.where_keyword,
      $.boolean_expression,
      ')',
    ),
    predicate: $ => seq(
      $.scalar_expression,
      choice(
        seq($.comparison_operator, $.scalar_expression),
        seq($.text_operator, $.scalar_expression),
        seq($.is_keyword, optional($.not_keyword), $.null_keyword),
      ),
    ),
    comparison_operator: _ => choice('=', '!=', '<>', '<', '<=', '>', '>='),
    text_operator: $ => choice($.like_keyword, $.ilike_keyword),

    scalar_expression: $ => choice(
      prec.left(1, seq($.scalar_expression, choice('+', '-'), $.scalar_expression)),
      prec.left(2, seq($.scalar_expression, choice('*', '/', '%'), $.scalar_expression)),
      prec.right(3, seq(choice('+', '-'), $.scalar_expression)),
      $.scalar_atom,
    ),
    scalar_atom: $ => choice(
      $.identifier,
      $.number,
      $.unit_literal,
      $.date,
      $.string,
      $.known_scalar_function,
      $.collection_transform,
      seq('(', $.scalar_expression, ')'),
    ),
    known_scalar_function: $ => choice(
      seq(
        choice(
          $.upper_keyword,
          $.lower_keyword,
          $.length_keyword,
          $.cardinality_keyword,
        ),
        '(',
        $.scalar_expression,
        ')',
      ),
      seq(
        choice(
          $.coalesce_keyword,
          $.concat_keyword,
          $.greatest_keyword,
          $.least_keyword,
        ),
        '(',
        $.scalar_expression,
        ',',
        commaSeparated($.scalar_expression),
        ')',
      ),
    ),
    collection_transform: $ => choice(
      seq(
        $.filter_keyword,
        '(',
        $.scalar_expression,
        $.as_keyword,
        field('binding', $.identifier),
        $.where_keyword,
        $.boolean_expression,
        ')',
      ),
      seq(
        $.map_keyword,
        '(',
        $.scalar_expression,
        $.as_keyword,
        field('binding', $.identifier),
        $.select_keyword,
        $.scalar_expression,
        ')',
      ),
    ),

    select_keyword: _ => keyword('select'),
    from_keyword: _ => keyword('from'),
    where_keyword: _ => keyword('where'),
    order_keyword: _ => keyword('order'),
    by_keyword: _ => keyword('by'),
    limit_keyword: _ => keyword('limit'),
    offset_keyword: _ => keyword('offset'),
    as_keyword: _ => keyword('as'),
    asc_keyword: _ => keyword('asc'),
    desc_keyword: _ => keyword('desc'),
    or_keyword: _ => keyword('or'),
    and_keyword: _ => keyword('and'),
    not_keyword: _ => keyword('not'),
    any_keyword: _ => keyword('any'),
    all_keyword: _ => keyword('all'),
    union_keyword: _ => keyword('union'),
    of_keyword: _ => keyword('of'),
    on_keyword: _ => keyword('on'),
    join_keyword: _ => keyword('join'),
    inner_keyword: _ => keyword('inner'),
    left_keyword: _ => keyword('left'),
    outer_keyword: _ => keyword('outer'),
    semi_keyword: _ => keyword('semi'),
    anti_keyword: _ => keyword('anti'),
    is_keyword: _ => keyword('is'),
    null_keyword: _ => keyword('null'),
    like_keyword: _ => keyword('like'),
    ilike_keyword: _ => keyword('ilike'),
    coalesce_keyword: _ => keyword('coalesce'),
    concat_keyword: _ => keyword('concat'),
    greatest_keyword: _ => keyword('greatest'),
    least_keyword: _ => keyword('least'),
    upper_keyword: _ => keyword('upper'),
    lower_keyword: _ => keyword('lower'),
    length_keyword: _ => keyword('length'),
    cardinality_keyword: _ => keyword('cardinality'),
    filter_keyword: _ => keyword('filter'),
    map_keyword: _ => keyword('map'),

    identifier: _ => /[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)*/,
    at_identifier: _ => /@[A-Za-z0-9_.-]+/,
    integer_literal: _ => /(?:0[xX][0-9a-fA-F](?:_?[0-9a-fA-F])*|0[oO][0-7](?:_?[0-7])*|0[bB][01](?:_?[01])*|\d(?:_?\d)*)/,
    positive_integer_literal: _ => /(?:0[xX](?:0_?)*[1-9a-fA-F](?:_?[0-9a-fA-F])*|0[oO](?:0_?)*[1-7](?:_?[0-7])*|0[bB](?:0_?)*1(?:_?[01])*|(?:0_?)*[1-9](?:_?\d)*)/,
    number: _ => /(?:0[xX][0-9A-Za-z_]+|0[oO][0-9A-Za-z_]+|0[bB][0-9A-Za-z_]+|\d[\d_]*(?:\.\d[\d_]*)?(?:[kKmMbB])?)/,
    unit_literal: _ => token(prec(2, /\d+(?:\.\d+)?[A-Za-z]+(?:-[A-Za-z]+)*/)),
    date: _ => token(prec(3, /\d{4}[-\/.]\d{1,2}[-\/.]\d{1,2}|\d{1,2}[-\/.]\d{1,2}[-\/.]\d{4}/)),
    string: _ => /'(?:''|\\.|[^'\\])*'|"(?:""|\\.|[^"\\])*"/,
    comment: _ => token(/#[^\r\n]*/),
  },
});
