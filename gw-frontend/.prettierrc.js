export default {
  tabWidth: 2,
  semi: false,
  singleQuote: true,
  jsxSingleQuote: true,
  // R6.55: Windows checkouts have CRLF; preserve whatever is there to avoid
  // mass-diff on first lint run. .editorconfig + .gitattributes enforce LF
  // for new files going forward.
  endOfLine: 'auto',
};
