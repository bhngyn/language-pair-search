/**
 * lpsq.mjs - the QUERY side of the Python package `language-pair-search` (lps), ported to plain JS.
 *
 * Mirrors src/language_pair_search/{textnorm,translit}.py, lexicon.expand and index.FTS_VERSION of the same
 * checkout. A browser can turn a user's query into the same SQLite FTS5 MATCH expression Python would build,
 * against an index built in Python with lps.index_text. Parity is the whole point: a word normalised or keyed
 * differently here silently misses.
 *
 * MUST be re-ported and re-verified (`python scripts/golden.py`, then `node --test 'tests/js/*.test.mjs'`) with
 * any change to normalize, the keys, the stemmers, fts_query or expand, and whenever KEY_VERSION or FTS_VERSION
 * changes. See the README, section "JavaScript query port".
 *
 * Scope: normalize, matchKey, ftsQuery, ftsScoped, expand (without a dictionary: only the Cyrillic-romanisation
 * groups, exactly as lexicon.expand does when dictionary.db is missing). Not ported: Edits, doc_freq,
 * find_places, the gazetteer, entities.
 *
 * Python's character classes (re \w \d \s, str.isalpha/isalnum/strip, unicodedata.combining) are embedded below
 * as range tables generated from Python 3.14 / Unicode 16.0 (`python scripts/golden.py --tables`), so they do not
 * depend on the JS engine's Unicode version. NFKC/NFKD and lower-casing use the engine (String#normalize,
 * String#toLowerCase); the golden code-point sweep checks those.
 *
 * Pure ES module, no dependencies; works in browsers and Node.
 */

export const KEY_VERSION = 3;       // translit.KEY_VERSION
export const FTS_VERSION = "3";     // index.FTS_VERSION
export const ROMAN_PREFIX = "zz";

// --------------------------------------------------------------------------- //
// Python Unicode classes (generated: `python scripts/golden.py --tables`)
// --------------------------------------------------------------------------- //

// Ranges as `gap[-len]` in base 36, gap from the previous range end. Python 3.14 / Unicode 16.0.0.
const TABLES = {
  word: "1c-9,8-p,5,2-p,1c,8-1,2,4-1,2-2,2-m,2-u,2-cp,5-b,f-4,8,2,3m-4,2-1,3-3,2,7,2-2,2,2-j,2-2a,2-3u,9-4l,2-11,3,7-14,20-q,5-3,1a-16,m-9,5-1,2-2q,2,g-1,8-e,3,h,2-t,u-2g,c,f-16,a-1,5,6-l,5,a,4,o-o,8-a,6-n,2-5,i-15,1n-1h,4,j,8-9,5-9,2-f,5-7,3-1,3-l,2-6,2,4-3,4,h,e-1,2-2,5-b,3-5,3,9-5,5-1,3-l,2-6,2-1,2-1,2-1,w-3,2,8-9,3-2,h-8,2-2,2-l,2-6,2-1,2-4,4,j,g-1,5-9,a,c-7,3-1,3-l,2-6,2-1,2-4,4,v-1,2-2,5-9,2-6,c,2-5,4-2,2-3,4-1,2,2-1,4-1,4-2,4-b,n,m-c,j-7,2-2,2-m,2-f,4,r-2,3,3-1,5-9,9-6,2,5-7,2-2,2-m,2-9,2-4,4,w-1,2-1,5-9,2-1,i-8,2-2,2-14,3,h,6-2,2-9,5-i,2-5,6-h,4-n,2-8,2,3-6,w-9,i-1b,2-1,d-6,a-9,14-1,2,2-4,2-n,2,2-9,2-1,a,3-4,2,a-9,3-3,x,w-j,d-7,2-z,s-4,38-16,l-a,7-5,5-3,4,4-1,8-2,5-c,d,2-9,7-11,2,6,3-16,2-98,2-3,3-6,2,2-3,3-14,2-3,3-w,2-3,3-6,2,2-3,3-e,2-1k,2-3,3-1u,f-j,4-f,h-2d,3-5,4-h7,3-g,2-p,6-22,4-a,8-h,e-i,f-h,f-c,2-2,g-1f,10,5,4-9,7-9,n-9,7-2g,8-4,3-x,2,6-1x,b-u,14-13,3-4,c-17,5-p,7-a,12-m,a-1g,18-9,7-9,e,2m-1a,i-7,4-9,16-t,e-1j,r-z,t-9,4-1c,3-a,6-16,3-2,16-3,2-5,2-1,4,6-5b,1t-7p,3-5,3-11,3-5,3-7,2,2,2,2-u,3-1g,2-6,2,4-2,2-6,4-3,3-5,5-c,6-2,2-6,38-1,3-5,6-a,7-c,2u,5,3-9,2,4-4,7,2,2,2-3,2-a,3-3,6-4,5,2-1l,k7-1n,27-l,hj-t,vh-6c,7-3,4-1,a,3-11,2,6,3-1j,8,h-m,a-6,2-6,2-6,2-6,2-6,2-6,2-6,2-6,29,d2-2,q-8,8-4,3-4,5-2d,7-2,2-2h,2-3,6-16,2-2l,4-3,b-v,1d-f,x-9,v-7,2-e,x-9,14-e,8x-533,1t-h3g,1w-19,3-7g,4-r,l-1a,h-u,3-27,14-8,3-2u,3-1u,3-1,2,2-7,m-f,2-2,2-3,2-m,e-5,b-1f,f-1d,t-9,p-5,4,2-1,2-11,b-m,q-s,8-1a,t-a,7-4,2-o,2-14,o-2,2-7,5-9,7-m,4,4-1d,2,4-1,3-4,3,2,p-2,3-a,8-2,d-5,3-5,3-5,a-6,2-6,2-16,2-d,7-36,e-9,7-8mb,d-m,5-1c,6it-a5,3-2x,13-6,d-4,6,2-9,2-c,2-4,2,2-1,2-1,2-2z,y-a2,j-1r,3-1h,15-b,39-4,2-3q,k-9,8-p,7-p,c-2g,4-5,3-5,3-5,3-2,10-b,2-p,2-i,2-1,2-e,3-d,z-3e,d-18,d-1k,i-1,6t-s,4-1c,h-q,5-z,a-t,6-11,b-t,3-z,5-7,2-4,17-4d,3-9,7-z,5-z,5-13,9-1f,d-a,2-e,2-6,2-1,2-a,2-e,2-6,2-1,4-1f,d-8m,a-l,b-7,p-5,2-15,2-8,1y-5,3,2-17,2-1,4,3-m,3-u,3-11,9-8,1d-i,2-1,6-w,5-p,1z-1j,5-j,3-1a,g-3,2-2,2-s,b-8,o-u,2-v,x-7,2-r,7-4,h-1h,b-l,3-q,6-p,o-6,29-20,1k-1e,e-1e,8-15,d-9,7-11,a-m,63-u,2-15,7-1,h-2,1o-13,9-l,c-3,s-h,1b-r,l-m,d-1g,r-t,2-1,3,e-18,x-o,8-9,a-z,g-9,5,3,9-y,4,d-1b,f-3,c-a,2,5-j,c-h,2-o,k-1,1s-6,2,2-3,2-e,2-9,8-1a,i-9,c-7,3-1,3-l,2-6,2-1,2-4,4,j,d-4,v-9,2,3,2-11,2,q,2,19-1g,j-3,6-9,6-2,v-1b,l-1,2,9-9,4n-1a,16-3,11-1b,l,c-9,13-16,e,8-9,7-j,t-q,m-b,5-6,56-17,39-2a,d-7,3,3-7,2-1,2-n,g,2,f-9,1z-7,3-12,h,2,t,b-13,8,m,c-19,k,j-20,5k-w,g-9,7-8,2-10,i,g-s,6-t,35-6,2-1,2-11,m,a-9,7-5,2-1,2-v,f,8-9,8n-i,g,2-c,2-x,t-9,2f,g-k,18-pl,2v-32,i-5f,219-2o,g-tr,i-5,q-32y,6-g6,5a2-t,j-9,1c7-fs,8-u,2-9,7-26,2-9,7-t,j-1b,h-3,d-9,2-6,2-k,6-i,c1-18,4-9,5j-2e,2y-22,6,1v-c,1t-1,2,t-4qf,9-yd,16-9,6w8-3,2-6,2-1,2-82,g,u-2,3,f-3,9-az,1s5-2y,6-c,4-8,8-9,387-9,153-j,d-j,31-o,3s-2c,2-1y,2-1,3,3-1,3-3,2-b,2,2-6,2-1s,2-3,3-7,2-6,2-r,2-3,2-4,2,4-6,2-9f,3-o,2-o,2-u,2-o,2-u,2-o,2-u,2-o,2-u,2-o,2-7,3-1d,1dt-u,7-5,7a-1p,43-18,b-6,3-9,5,8y-t,j-17,5-9,d3-r,5-9,5z-t,3-a,di-6,2-3,2-1,2-e,2-5g,3-8,1d-1v,8,5-9,m0-1m,2-2,2-3,25-18,2-e,5f-3,2-q,2-1,2,3,2-9,2-3,2,2,7,5,2,2,2-2,2-1,2,3,2,2,2,2,2-1,2,3-3,2-6,2-3,2-3,2,2-9,2-g,6-2,2-4,2-g,g5-c,25g-9,sn-wyn,x-37d,7-65,3-4g1,f-5rk,g-h9,1wj-f1,15v-3t6,6-38f",
  alnum: "1c-9,8-p,7-p,1c,8-1,2,4-1,2-2,2-m,2-u,2-cp,5-b,f-4,8,2,3m-4,2-1,3-3,2,7,2-2,2,2-j,2-2a,2-3u,9-4l,2-11,3,7-14,20-q,5-3,1a-16,m-9,5-1,2-2q,2,g-1,8-e,3,h,2-t,u-2g,c,f-16,a-1,5,6-l,5,a,4,o-o,8-a,6-n,2-5,i-15,1n-1h,4,j,8-9,5-9,2-f,5-7,3-1,3-l,2-6,2,4-3,4,h,e-1,2-2,5-b,3-5,3,9-5,5-1,3-l,2-6,2-1,2-1,2-1,w-3,2,8-9,3-2,h-8,2-2,2-l,2-6,2-1,2-4,4,j,g-1,5-9,a,c-7,3-1,3-l,2-6,2-1,2-4,4,v-1,2-2,5-9,2-6,c,2-5,4-2,2-3,4-1,2,2-1,4-1,4-2,4-b,n,m-c,j-7,2-2,2-m,2-f,4,r-2,3,3-1,5-9,9-6,2,5-7,2-2,2-m,2-9,2-4,4,w-1,2-1,5-9,2-1,i-8,2-2,2-14,3,h,6-2,2-9,5-i,2-5,6-h,4-n,2-8,2,3-6,w-9,i-1b,2-1,d-6,a-9,14-1,2,2-4,2-n,2,2-9,2-1,a,3-4,2,a-9,3-3,x,w-j,d-7,2-z,s-4,38-16,l-a,7-5,5-3,4,4-1,8-2,5-c,d,2-9,7-11,2,6,3-16,2-98,2-3,3-6,2,2-3,3-14,2-3,3-w,2-3,3-6,2,2-3,3-e,2-1k,2-3,3-1u,f-j,4-f,h-2d,3-5,4-h7,3-g,2-p,6-22,4-a,8-h,e-i,f-h,f-c,2-2,g-1f,10,5,4-9,7-9,n-9,7-2g,8-4,3-x,2,6-1x,b-u,14-13,3-4,c-17,5-p,7-a,12-m,a-1g,18-9,7-9,e,2m-1a,i-7,4-9,16-t,e-1j,r-z,t-9,4-1c,3-a,6-16,3-2,16-3,2-5,2-1,4,6-5b,1t-7p,3-5,3-11,3-5,3-7,2,2,2,2-u,3-1g,2-6,2,4-2,2-6,4-3,3-5,5-c,6-2,2-6,38-1,3-5,6-a,7-c,2u,5,3-9,2,4-4,7,2,2,2-3,2-a,3-3,6-4,5,2-1l,k7-1n,27-l,hj-t,vh-6c,7-3,4-1,a,3-11,2,6,3-1j,8,h-m,a-6,2-6,2-6,2-6,2-6,2-6,2-6,2-6,29,d2-2,q-8,8-4,3-4,5-2d,7-2,2-2h,2-3,6-16,2-2l,4-3,b-v,1d-f,x-9,v-7,2-e,x-9,14-e,8x-533,1t-h3g,1w-19,3-7g,4-r,l-1a,h-u,3-27,14-8,3-2u,3-1u,3-1,2,2-7,m-f,2-2,2-3,2-m,e-5,b-1f,f-1d,t-9,p-5,4,2-1,2-11,b-m,q-s,8-1a,t-a,7-4,2-o,2-14,o-2,2-7,5-9,7-m,4,4-1d,2,4-1,3-4,3,2,p-2,3-a,8-2,d-5,3-5,3-5,a-6,2-6,2-16,2-d,7-36,e-9,7-8mb,d-m,5-1c,6it-a5,3-2x,13-6,d-4,6,2-9,2-c,2-4,2,2-1,2-1,2-2z,y-a2,j-1r,3-1h,15-b,39-4,2-3q,k-9,8-p,7-p,c-2g,4-5,3-5,3-5,3-2,10-b,2-p,2-i,2-1,2-e,3-d,z-3e,d-18,d-1k,i-1,6t-s,4-1c,h-q,5-z,a-t,6-11,b-t,3-z,5-7,2-4,17-4d,3-9,7-z,5-z,5-13,9-1f,d-a,2-e,2-6,2-1,2-a,2-e,2-6,2-1,4-1f,d-8m,a-l,b-7,p-5,2-15,2-8,1y-5,3,2-17,2-1,4,3-m,3-u,3-11,9-8,1d-i,2-1,6-w,5-p,1z-1j,5-j,3-1a,g-3,2-2,2-s,b-8,o-u,2-v,x-7,2-r,7-4,h-1h,b-l,3-q,6-p,o-6,29-20,1k-1e,e-1e,8-15,d-9,7-11,a-m,63-u,2-15,7-1,h-2,1o-13,9-l,c-3,s-h,1b-r,l-m,d-1g,r-t,2-1,3,e-18,x-o,8-9,a-z,g-9,5,3,9-y,4,d-1b,f-3,c-a,2,5-j,c-h,2-o,k-1,1s-6,2,2-3,2-e,2-9,8-1a,i-9,c-7,3-1,3-l,2-6,2-1,2-4,4,j,d-4,v-9,2,3,2-11,2,q,2,19-1g,j-3,6-9,6-2,v-1b,l-1,2,9-9,4n-1a,16-3,11-1b,l,c-9,13-16,e,8-9,7-j,t-q,m-b,5-6,56-17,39-2a,d-7,3,3-7,2-1,2-n,g,2,f-9,1z-7,3-12,h,2,t,b-13,8,m,c-19,k,j-20,5k-w,g-9,7-8,2-10,i,g-s,6-t,35-6,2-1,2-11,m,a-9,7-5,2-1,2-v,f,8-9,8n-i,g,2-c,2-x,t-9,2f,g-k,18-pl,2v-32,i-5f,219-2o,g-tr,i-5,q-32y,6-g6,5a2-t,j-9,1c7-fs,8-u,2-9,7-26,2-9,7-t,j-1b,h-3,d-9,2-6,2-k,6-i,c1-18,4-9,5j-2e,2y-22,6,1v-c,1t-1,2,t-4qf,9-yd,16-9,6w8-3,2-6,2-1,2-82,g,u-2,3,f-3,9-az,1s5-2y,6-c,4-8,8-9,387-9,153-j,d-j,31-o,3s-2c,2-1y,2-1,3,3-1,3-3,2-b,2,2-6,2-1s,2-3,3-7,2-6,2-r,2-3,2-4,2,4-6,2-9f,3-o,2-o,2-u,2-o,2-u,2-o,2-u,2-o,2-u,2-o,2-7,3-1d,1dt-u,7-5,7a-1p,43-18,b-6,3-9,5,8y-t,j-17,5-9,d3-r,5-9,5z-t,3-a,di-6,2-3,2-1,2-e,2-5g,3-8,1d-1v,8,5-9,m0-1m,2-2,2-3,25-18,2-e,5f-3,2-q,2-1,2,3,2-9,2-3,2,2,7,5,2,2,2-2,2-1,2,3,2,2,2,2,2-1,2,3-3,2-6,2-3,2-3,2,2-9,2-g,6-2,2-4,2-g,g5-c,25g-9,sn-wyn,x-37d,7-65,3-4g1,f-5rk,g-h9,1wj-f1,15v-3t6,6-38f",
  letter: "1t-p,7-p,1c,8-1,2,4-1,2-2,2-m,2-u,2-cp,5-b,f-4,8,2,3m-4,2-1,3-3,2,7,2-2,2,2-j,2-2a,2-3u,9-4l,2-11,3,7-14,20-q,5-3,1a-16,10-1,2-2q,2,g-1,8-1,b-2,3,h,2-t,u-2g,c,p-w,a-1,5,6-l,5,a,4,o-o,8-a,6-n,2-5,i-15,1n-1h,4,j,8-9,g-f,5-7,3-1,3-l,2-6,2,4-3,4,h,e-1,2-2,f-1,3-5,3,9-5,5-1,3-l,2-6,2-1,2-1,2-1,w-3,2,k-2,h-8,2-2,2-l,2-6,2-1,2-4,4,j,g-1,o,c-7,3-1,3-l,2-6,2-1,2-4,4,v-1,2-2,g-6,c,2-5,4-2,2-3,4-1,2,2-1,4-1,4-2,4-b,n,w-2,j-7,2-2,2-m,2-f,4,r-2,3,3-1,n-6,2,5-7,2-2,2-m,2-9,2-4,4,w-1,2-1,g-1,i-8,2-2,2-14,3,h,6-2,2-9,f-8,2-5,6-h,4-n,2-8,2,3-6,1n-1b,2-1,d-6,1n-1,2,2-4,2-n,2,2-9,2-1,a,3-4,2,m-3,x,16-9,d-7,2-z,s-4,38-16,l,h-5,5-3,4,4-1,8-2,5-c,d,i-11,2,6,3-16,2-98,2-3,3-6,2,2-3,3-14,2-3,3-w,2-3,3-6,2,2-3,3-e,2-1k,2-3,3-1u,f-j,4-f,h-2d,3-5,4-h7,3-g,2-p,6-22,4-a,8-h,e-i,f-h,f-c,2-2,g-1f,10,5,k-9,13-2g,8-4,3-x,2,6-1x,b-u,1e-t,3-4,c-17,5-p,h,12-m,a-1g,2b,2m-1a,i-7,1j-t,e-1,b-17,r-z,16-2,b-z,3-a,6-16,3-2,16-3,2-5,2-1,4,6-5b,1t-7p,3-5,3-11,3-5,3-7,2,2,2,2-u,3-1g,2-6,2,4-2,2-6,4-3,3-5,5-c,6-2,2-6,38-1,3-5,6-a,7-c,2u,5,3-9,2,4-4,7,2,2,2-3,2-a,3-3,6-4,5,2-1l,k7-1n,27-l,hj-t,vh-6c,7-3,4-1,a,3-11,2,6,3-1j,8,h-m,a-6,2-6,2-6,2-6,2-6,2-6,2-6,2-6,29,d2-2,q-8,8-4,3-4,5-2d,7-2,2-2h,2-3,6-16,2-2l,4-3,b-v,1d-f,x-9,v-7,2-e,x-9,14-e,8x-533,1t-h3g,1w-19,3-7g,4-f,b-1,l-1a,h-u,3-27,14-8,3-2u,3-1u,3-1,2,2-7,m-f,2-2,2-3,2-m,e-5,b-1f,f-1d,1r-5,4,2-1,c-r,b-m,q-s,8-1a,t,h-4,2-9,b-4,2-14,o-2,2-7,l-m,4,4-1d,2,4-1,3-4,3,2,p-2,3-a,8-2,d-5,3-5,3-5,a-6,2-6,2-16,2-d,7-36,u-8mb,d-m,5-1c,6it-a5,3-2x,13-6,d-4,6,2-9,2-c,2-4,2,2-1,2-1,2-2z,y-a2,j-1r,3-1h,15-b,39-4,2-3q,11-p,7-p,c-2g,4-5,3-5,3-5,3-2,10-b,2-p,2-i,2-1,2-e,3-d,z-3e,d-18,d-1k,i-1,6t-s,4-1c,h-q,5-z,a-t,6-11,b-t,3-z,5-7,2-4,17-4d,j-z,5-z,5-13,9-1f,d-a,2-e,2-6,2-1,2-a,2-e,2-6,2-1,4-1f,d-8m,a-l,b-7,p-5,2-15,2-8,1y-5,3,2-17,2-1,4,3-m,3-u,3-11,9-8,1d-i,2-1,6-w,5-p,1z-1j,5-j,3-1a,g-3,2-2,2-s,b-8,o-u,2-v,x-7,2-r,7-4,h-1h,b-l,3-q,6-p,o-6,29-20,1k-1e,e-1e,8-15,13-r,a-m,63-u,2-15,7-1,h-2,1o-13,9-l,c-3,s-h,1b-r,l-m,d-1g,r-j,c-1,3,e-18,x-o,r-z,u,3,9-y,4,d-1b,f-3,m,2,5-j,c-h,2-o,k-1,1s-6,2,2-3,2-e,2-9,8-1a,13-7,3-1,3-l,2-6,2-1,2-4,4,j,d-4,v-9,2,3,2-11,2,q,2,19-1g,j-3,l-2,v-1b,l-1,2,55-1a,16-3,11-1b,l,1o-16,e,20-q,w-1,5-6,56-17,39-1r,b-8,d-7,3,3-7,2-1,2-n,g,2,2n-7,3-12,h,2,t,b-13,8,m,c-19,k,j-20,5k-w,w-8,2-10,i,q-i,6-t,35-6,2-1,2-11,m,q-5,2-1,2-v,f,94-i,g,2-c,2-x,3h,g-k,18-pl,2v-32,i-5f,219-2o,g-tr,i-5,q-32y,6-g6,5a2-t,1cz-fs,8-u,i-26,i-t,j-1b,h-3,o-6,2-k,6-i,c1-18,5w-2e,2y-22,6,1v-c,1t-1,2,t-4qf,9-yd,16-9,6w8-3,2-6,2-1,2-82,g,u-2,3,f-3,9-az,1s5-2y,6-c,4-8,8-9,4dj-j,d-j,31-o,3s-2c,2-1y,2-1,3,3-1,3-3,2-b,2,2-6,2-1s,2-3,3-7,2-6,2-r,2-3,2-4,2,4-6,2-9f,3-o,2-o,2-u,2-o,2-u,2-o,2-u,2-o,2-u,2-o,2-7,1f9-u,7-5,7a-1p,43-18,b-6,h,8y-t,j-17,dh-r,6d-t,3,ds-6,2-3,2-1,2-e,2-5g,3-8,1d-1v,8,me-1m,2-2,2-3,25-18,2-e,5f-3,2-q,2-1,2,3,2-9,2-3,2,2,7,5,2,2,2-2,2-1,2,3,2,2,2,2,2-1,2,3-3,2-6,2-3,2-3,2,2-9,2-g,6-2,2-4,2-g,g5-c,2yc-wyn,x-37d,7-65,3-4g1,f-5rk,g-h9,1wj-f1,15v-3t6,6-38f",
  digit: "1c-9,17r-9,3r-9,5j-9,bh-9,3b-9,3b-9,3b-9,3b-9,3b-9,3b-9,3b-9,3b-9,3b-9,2p-9,3b-9,1z-9,7r-9,1z-9,1fr-9,13-9,8d-9,3l-9,4n-9,7-9,53-9,2f-9,3r-9,7-9,r7r-9,iv-9,13-9,5j-9,n-9,2f-9,bb-9,gev-9,13b-9,1on-9,7-9,m5-9,3l-9,1p-9,41-9,7r-9,9j-9,3b-9,af-9,2v-9,7-j,25-9,br-9,2v-9,if-9,2f-9,6v-9,1z-9,br-9,d07-9,1t3-9,2f-9,3r-9,ev-9,iuv-9,251-1d,1tt-9,br-9,dz-9,6w-9,nq-9,3o7-9",
  space: "9-4,f-4,2t,r,4bk,1vk-a,u-1,6,1c,335",
  alpha: "1t-p,7-p,1c,b,5,6-m,2-u,2-cp,5-b,f-4,8,2,3m-4,2-1,3-3,2,7,2-2,2,2-j,2-2a,2-3u,9-4l,2-11,3,7-14,20-q,5-3,1a-16,10-1,2-2q,2,g-1,8-1,b-2,3,h,2-t,u-2g,c,p-w,a-1,5,6-l,5,a,4,o-o,8-a,6-n,2-5,i-15,1n-1h,4,j,8-9,g-f,5-7,3-1,3-l,2-6,2,4-3,4,h,e-1,2-2,f-1,b,9-5,5-1,3-l,2-6,2-1,2-1,2-1,w-3,2,k-2,h-8,2-2,2-l,2-6,2-1,2-4,4,j,g-1,o,c-7,3-1,3-l,2-6,2-1,2-4,4,v-1,2-2,g,i,2-5,4-2,2-3,4-1,2,2-1,4-1,4-2,4-b,n,1h-7,2-2,2-m,2-f,4,r-2,3,3-1,v,5-7,2-2,2-m,2-9,2-4,4,w-1,2-1,g-1,i-8,2-2,2-14,3,h,6-2,9-2,p-5,6-h,4-n,2-8,2,3-6,1n-1b,2-1,d-6,1n-1,2,2-4,2-n,2,2-9,2-1,a,3-4,2,m-3,x,1s-7,2-z,s-4,38-16,l,h-5,5-3,4,4-1,8-2,5-c,d,i-11,2,6,3-16,2-98,2-3,3-6,2,2-3,3-14,2-3,3-w,2-3,3-6,2,2-3,3-e,2-1k,2-3,3-1u,12-f,h-2d,3-5,4-h7,3-g,2-p,6-22,7-7,8-h,e-i,f-h,f-c,2-2,g-1f,10,5,1w-2g,8-4,3-x,2,6-1x,b-u,1e-t,3-4,c-17,5-p,1j-m,a-1g,2b,2m-1a,i-7,1j-t,e-1,b-17,r-z,16-2,b-z,3-a,6-16,3-2,16-3,2-5,2-1,4,6-5b,1t-7p,3-5,3-11,3-5,3-7,2,2,2,2-u,3-1g,2-6,2,4-2,2-6,4-3,3-5,5-c,6-2,2-6,39,e,h-c,2u,5,3-9,2,4-4,7,2,2,2-3,2-a,3-3,6-4,5,1h-1,22k-6c,7-3,4-1,d-11,2,6,3-1j,8,h-m,a-6,2-6,2-6,2-6,2-6,2-6,2-6,2-6,29,d2-1,17-4,6-1,5-2d,7-2,2-2h,2-3,6-16,2-2l,i-v,1d-f,e9-533,1t-h3g,1w-19,3-7g,4-f,b-1,l-1a,h-u,3-1x,1e-8,3-2u,3-1u,3-1,2,2-7,m-f,2-2,2-3,2-m,u-1f,f-1d,1r-5,4,2-1,c-r,b-m,q-s,8-1a,t,h-4,2-9,b-4,2-14,o-2,2-7,l-m,4,4-1d,2,4-1,3-4,3,2,p-2,3-a,8-2,d-5,3-5,3-5,a-6,2-6,2-16,2-d,7-36,u-8mb,d-m,5-1c,6it-a5,3-2x,13-6,d-4,6,2-9,2-c,2-4,2,2-1,2-1,2-2z,y-a2,j-1r,3-1h,15-b,39-4,2-3q,11-p,7-p,c-2g,4-5,3-5,3-5,3-2,10-b,2-p,2-i,2-1,2-e,3-d,z-3e,au-s,4-1c,1c-v,e-j,2-7,7-11,b-t,3-z,5-7,1d-4d,j-z,5-z,5-13,9-1f,d-a,2-e,2-6,2-1,2-a,2-e,2-6,2-1,4-1f,d-8m,a-l,b-7,p-5,2-15,2-8,1y-5,3,2-17,2-1,4,3-m,b-m,a-u,1u-i,2-1,b-l,b-p,1z-1j,7-1,1t,g-3,2-2,2-s,17-s,4-s,10-7,2-r,s-1h,b-l,b-i,e-h,33-20,1k-1e,e-1e,e-z,13-r,a-m,6z-15,7-1,h-2,1o-s,b,9-l,17-h,1b-k,s-m,d-1g,1m-1,3,e-18,x-o,r-z,u,3,9-y,4,d-1b,f-3,m,2,10-h,2-o,k-1,1s-6,2,2-3,2-e,2-9,8-1a,13-7,3-1,3-l,2-6,2-1,2-4,4,j,d-4,v-9,2,3,2-11,2,q,2,19-1g,j-3,l-2,v-1b,l-1,2,55-1a,16-3,11-1b,l,1o-16,e,20-q,12-6,56-17,39-1r,w-7,3,3-7,2-1,2-n,g,2,2n-7,3-12,h,2,t,b-13,8,m,c-19,k,j-20,5k-w,w-8,2-10,i,1e-t,35-6,2-1,2-11,m,q-5,2-1,2-v,f,94-i,g,2-c,2-x,3h,28-pl,6f-5f,219-2o,g-tr,i-5,q-32y,6-g6,5a2-t,1cz-fs,8-u,i-26,i-t,j-1b,h-3,w-k,6-i,c1-18,5w-1r,3l-22,6,1v-c,1t-1,2,t-4qf,9-yd,16-9,6w8-3,2-6,2-1,2-82,g,u-2,3,f-3,9-az,1s5-2y,6-c,4-8,8-9,4mf-2c,2-1y,2-1,3,3-1,3-3,2-b,2,2-6,2-1s,2-3,3-7,2-6,2-r,2-3,2-4,2,4-6,2-9f,3-o,2-o,2-u,2-o,2-u,2-o,2-u,2-o,2-u,2-o,2-7,1f9-u,7-5,7a-1p,43-18,b-6,h,8y-t,j-17,dh-r,6d-t,3,ds-6,2-3,2-1,2-e,2-5g,1o-1v,8,xh-3,2-q,2-1,2,3,2-9,2-3,2,2,7,5,2,2,2-2,2-1,2,3,2,2,2,2,2-1,2,3-3,2-6,2-3,2-3,2,2-9,2-g,6-2,2-4,2-g,3et-wyn,x-37d,7-65,3-4g1,f-5rk,g-h9,1wj-f1,15v-3t6,6-38f",
  combining: "lc-26,2-v,7o-4,7e-18,2,2-1,2-1,2,21-a,1d-k,h,2u-6,3-5,3-1,2-3,10,v-q,4h-8,a,p-3,2-8,2-2,2-4,18-2,1o-8,17-n,2-s,1p,h,4-3,2w,h,1d,1q,h,33,h,33,h,3k,33,h,8-1,2u,h,32-1,h,3h,32-2,e-3,31-2,e-3,25-1,s,2,2,1k-1,2,6-3,3,2-2,2-1,1r,35,2-1,2b,k0-2,qd-1,v,4e,b,5o,40-2,64-1,20,l-7,3,1d-d,2-f,2u,g,13-8,1j-1,1n,c-1,1w,49-2,2-c,2-6,5,7,4-1,5j-1r,k1-c,5,4-b,2db-2,3y,2p-v,ff-5,2y-1,n9x,5-9,x-1,29-1,7p,12,48,s-h,1m-2,12,2o,d,6o,2-2,3-1,6-1,2,1h,6v,fn5,le-f,r2,6b,46-4,1ar,2,15-2,5,4m-1,fy-3,1u-4,8u-1,29-2,1z-a,1e-3,5d,16,f,1m-1,1y-2,1d-1,1r,25,a,2z-1,4z-1,29-1,h,p-6,4-4,2i-2,36,4,o,2s-1,70-1,3j,3b-1,38,7i-1,77-1,5,4d,2c,j,2a,bq,77,2-1,2a,bu-1,d0t,1xd-4,1o-6,xm-1,f59,43r-4,4-5,9-7,3-6,v-3,45-2,2po-6,2-g,3-6,2-1,2-4,2t,4h-6,ag,1q-3,e5-3,73-1,kh-6,32-6",
};

function decodeRanges(s) {
  const out = [];
  let prev = 0;
  for (const part of s.split(",")) {
    const [a, b] = part.split("-");
    const st = prev + parseInt(a, 36);
    const en = st + (b ? parseInt(b, 36) : 0);
    out.push([st, en]);
    prev = en;
  }
  return out;
}

function cls(s) {
  const hex = (c) => "\\u{" + c.toString(16) + "}";
  return decodeRanges(s).map(([a, b]) => (a === b ? hex(a) : hex(a) + "-" + hex(b))).join("");
}

const W = cls(TABLES.word);        // re \w
const AN = cls(TABLES.alnum);      // [^\W_]  (= str.isalnum per char)
const LT = cls(TABLES.letter);     // [^\W\d_]
const D = cls(TABLES.digit);       // re \d
const S = cls(TABLES.space);       // re \s  (= str.isspace, what str.strip() strips)
const AL = cls(TABLES.alpha);      // str.isalpha per char
const CB = cls(TABLES.combining);  // unicodedata.combining(c) != 0

const RE_ISALNUM_CH = new RegExp(`^[${AN}]$`, "u");
const RE_ISALPHA = new RegExp(`^[${AL}]+$`, "u");
const RE_COMBINING = new RegExp(`[${CB}]`, "gu");
const RE_STRIP = new RegExp(`^[${S}]+|[${S}]+$`, "gu");

const isAlnumCh = (c) => RE_ISALNUM_CH.test(c);
const isAlpha = (s) => s.length > 0 && RE_ISALPHA.test(s);
const pyStrip = (s) => s.replace(RE_STRIP, "");

function cpLen(s) {
  let n = 0;
  for (const _ of s) n++;
  return n;
}

function translate(s, map) {
  let out = "";
  for (const c of s) {
    const r = map.get(c);
    out += r === undefined ? c : r;
  }
  return out;
}

// --------------------------------------------------------------------------- //
// textnorm: normalisation
// --------------------------------------------------------------------------- //

const AR_MARKS = /[ؐ-ًؚ-ٰٟۖ-ۭـ]/gu;
const INVISIBLE = "\u200b\u200c\u200d\u200e\u200f\u2060\u00ad\ufeff";
const TRANS = new Map([
  ["أ", "ا"], ["إ", "ا"], ["آ", "ا"], ["ٱ", "ا"],
  ["ى", "ي"], ["ئ", "ي"], ["ؤ", "و"], ["ة", "ه"],
  ["ک", "ك"], ["ی", "ي"], ["ە", "ه"], ["ۀ", "ه"],
  ["ё", "е"], ["Ё", "е"],
]);
for (let i = 0; i < 10; i++) {
  TRANS.set(String.fromCharCode(0x0660 + i), String(i));
  TRANS.set(String.fromCharCode(0x06f0 + i), String(i));
}
for (const c of INVISIBLE) TRANS.set(c, "");

const AR_PREFIXES = ["وال", "بال", "كال", "فال", "لل", "ال", "و", "ف", "ب", "ل", "ك", "س"];
const ARABIC_AT0 = /^[\u0600-\u06ff]/u;        // textnorm._ARABIC.match (first character)
const TOKEN = new RegExp(`[${W}\u0600-\u06ff]+`, "gu");

const LC = "a-zЀ-ӿ";
const PROTECT_SRC = `(?<![^${S}])(?:https?://|www\\.|t\\.me/|@)[^${S}]+|[${W}.+\\-]+@[${W}\\-]+(?:\\.[${W}][${W}\\-]*)+`;
const PROTECT = new RegExp(PROTECT_SRC, "u");
const PROTECT_G = new RegExp(PROTECT_SRC, "gu");
const LEET_AT = new RegExp(`(?<=[${LC}])[@$](?=[${LC}])`, "gu");
const LEET_0 = new RegExp(`(?<=[${LC}])0(?![${D}])|(?<![${D}])0(?=[${LC}])`, "gu");
const LEET_MAP = { "@": "a", $: "s" };
const SPACED = new RegExp(`(?<![${AN}])[${LC}]([ \\-_.*·•])(?:[${LC}]\\1){2,}[${LC}](?![${AN}])`, "gu");
const SEPS = /[ \-_.*·•]/gu;
const MIXED = new RegExp(`(?<![${AN}])(?=[${AN}]*[a-z])(?=[${AN}]*[Ѐ-ӿ])[${AN}]+`, "gu");
const REPEAT = new RegExp(`([${LT}])\\1{2,}`, "gu");
const LAT_TWINS = "aeopcxykmtbhi";
const CYR_TWINS = "аеорсхукмтвні";
const TO_CYR = new Map([...LAT_TWINS].map((c, i) => [c, CYR_TWINS[i]]));
const TO_LAT = new Map([...CYR_TWINS].map((c, i) => [c, LAT_TWINS[i]]));

function fixMixed(w) {
  let cy = 0, la = 0;
  for (const c of w) {
    if (c >= "Ѐ" && c <= "ӿ") cy++;
    else if (c >= "a" && c <= "z") la++;
  }
  return cy > la ? translate(w, TO_CYR) : la > cy ? translate(w, TO_LAT) : w;
}

function deobfuscate(t) {
  if (t.includes("@") || t.includes("$")) t = t.replace(LEET_AT, (m) => LEET_MAP[m]);
  if (t.includes("0")) t = t.replace(LEET_0, "o");
  t = t.replace(SPACED, (m) => m.replace(SEPS, ""));
  t = t.replace(MIXED, (m) => fixMixed(m));
  return t.replace(REPEAT, "$1");
}

/** textnorm.normalize: applied identically to documents (index side, in Python) and queries. */
export function normalize(text) {
  if (!text) return "";
  let t = text.normalize("NFKC");
  t = t.replace(AR_MARKS, "");
  t = translate(t, TRANS).toLowerCase();
  if (!(t.includes("@") || t.includes("://") || t.includes("www.") || t.includes("t.me/")) || !PROTECT.test(t)) {
    return deobfuscate(t);
  }
  const out = [];                                  // urls, @usernames and e-mails stay as written
  let pos = 0;
  for (const m of t.matchAll(PROTECT_G)) {
    out.push(deobfuscate(t.slice(pos, m.index)));
    out.push(m[0]);
    pos = m.index + m[0].length;
  }
  out.push(deobfuscate(t.slice(pos)));
  return out.join("");
}

function tokenize(s) {
  return s.match(TOKEN) || [];
}

function stripPrefix(tok) {
  if (!ARABIC_AT0.test(tok)) return tok;
  for (const p of AR_PREFIXES) {
    if (tok.startsWith(p) && cpLen(tok) - cpLen(p) >= 3) return tok.slice(p.length);
  }
  return tok;
}

// --------------------------------------------------------------------------- //
// translit: keys and stemmers
// --------------------------------------------------------------------------- //

const CY = new Map(Object.entries({
  "а": "a", "б": "b", "в": "v", "г": "g", "ґ": "g", "д": "d", "е": "e", "ё": "e", "є": "ie",
  "ж": "zh", "з": "z", "и": "i", "і": "i", "ї": "i", "й": "i", "к": "k", "л": "l", "м": "m",
  "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "q",
  "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "i", "ь": "", "э": "e",
  "ю": "iu", "я": "ia", "ў": "u",
}));
const LAT_MULTI = [["shch", "shch"], ["tch", "ch"], ["sch", "shch"], ["kh", "q"], ["zh", "zh"],
  ["ch", "ch"], ["sh", "sh"], ["ts", "ts"], ["tz", "ts"], ["ph", "f"], ["ou", "u"]];
const LAT_ONE = new Map(Object.entries({ q: "k", h: "g", x: "ks", c: "k", w: "v", j: "i", y: "i" }));
const FOLD_VOWELS = new Map([["e", "i"], ["o", "u"]]);
const CYRILLIC = /[Ѐ-ӿ]/u;
const ARABIC = /[\u0600-\u06ff]/u;
const LATIN = /[a-z]/u;
const APOS = /[’'ʼʻ`ʿʾ‘´]/gu;
const AR_ARTICLE = ["وال", "بال", "فال", "كال", "لل", "ال"];
const LAT_ARTICLE = new Set(["al", "el", "ad", "ed", "ar", "er", "as", "es", "at", "et", "an", "en", "az", "ez",
  "ash", "esh", "adh", "ath", "ad", "ud", "ul", "ur"]);

function finish(s) {
  return translate(s, FOLD_VOWELS).replace(/([^\n])\1+/gu, "$1");
}

function stripMarks(s) {
  return s.normalize("NFKD").replace(RE_COMBINING, "");
}

function cyKey(word) {
  const w = word.toLowerCase().replaceAll("ё", "е");
  let out = "";
  for (const c of w) {
    if (isAlnumCh(c)) {
      const r = CY.get(c);
      out += r === undefined ? c : r;
    }
  }
  return finish(out);
}

function latinKey(word) {
  let w = stripMarks(word).toLowerCase().replace(APOS, "");
  w = w.replace(/(?<=[aeiou])y(?=[aeiou])/gu, "");
  w = w.replace(/^y(?=[ao])/u, "i");
  w = w.replaceAll("yo", "e").replaceAll("jo", "e");
  const cps = Array.from(w);
  const out = [];
  let i = 0;
  outer: while (i < cps.length) {
    for (const [a, b] of LAT_MULTI) {
      let ok = i + a.length <= cps.length;
      for (let k = 0; ok && k < a.length; k++) if (cps[i + k] !== a[k]) ok = false;
      if (ok) {
        out.push(b);
        i += a.length;
        continue outer;
      }
    }
    const c = cps[i];
    if (isAlnumCh(c)) {
      const r = LAT_ONE.get(c);
      out.push(r === undefined ? c : r);
    }
    i += 1;
  }
  return finish(out.join(""));
}

function scriptOf(word) {
  if (ARABIC.test(word)) return "ar";
  if (CYRILLIC.test(word)) return "cy";
  if (LATIN.test(stripMarks(word).toLowerCase())) return "la";
  return "";
}

// Arabic / Persian personal names (KEY_VERSION 3): translit._name_fold / join_keys. Applied to word keys in
// wordKey / matchKey only, never in latinKey / cyKey (those also make the index's ROMAN_PREFIX tokens).
const NAME_FOLDS = [["mu?[gq]am[ai]d", "mugamad"], ["a[gq]m[ai]d", "agmad"], ["[gq]usa?in", "gusin"],
  ["ius[iu]f", "iusuf"]];
const NAME_FOLDS_RX = NAME_FOLDS.map(([p, c]) => [new RegExp(`^(?:${p})$`, "u"), c]);
const ABD_WORDS = new Set(["abd", "abdil", "abdul", "abdal", "abdur", "abdus"]);
const ABD_ALLAH = "abd[aiu]?la[gq]?";
const ABD_JOINED = "abd[aiu]l([a-z]{3,})|abd[aiu]([rstdznl][a-z]{2,})";
const ALLAH = "[aiu]?la[gq]?";
const ABD_ALLAH_RX = new RegExp(`^(?:${ABD_ALLAH})$`, "u");
const ABD_JOINED_RX = new RegExp(`^(?:${ABD_JOINED})$`, "u");
const ALLAH_RX = new RegExp(`^(?:${ALLAH})$`, "u");
const NAME_ARTICLES = new Set(["al", "el", "ul", "аль", "эль", "ель", "уль", "ал", "эл"]);
const CY_ARTICLE = new Set(["аль", "ал", "эль", "ель", "эд", "ас", "аш", "ад", "ар", "ат", "ан", "аз", "уль", "ур"]);

function nameFold(key) {
  if (!/^[amgqi]/u.test(key)) return key;
  for (const [rx, canon] of NAME_FOLDS_RX) if (rx.test(key)) return canon;
  if (key.startsWith("abd")) {
    if (ABD_WORDS.has(key)) return "abd";
    if (ABD_ALLAH_RX.test(key)) return "abd lag";
    const m = ABD_JOINED_RX.exec(key);
    if (m) return "abd " + (m[1] || m[2]);
  }
  return key;
}

function isArticle(t) {
  t = stripMarks(t).toLowerCase();
  return LAT_ARTICLE.has(t) || CY_ARTICLE.has(t);
}

function joinKeys(toks, keys) {
  const out = [];
  let prev = "";
  for (let i = 0; i < toks.length && i < keys.length; i++) {
    const t = toks[i];
    let k = keys[i];
    if (!k) continue;
    if (prev === "abd" && (scriptOf(t) === "la" || scriptOf(t) === "cy")) {
      if (isArticle(t) && keys.slice(i + 1).some((x) => x)) continue;   // only when a name follows
      if (ALLAH_RX.test(k)) k = "lag";
    } else if (out.length && NAME_ARTICLES.has(stripMarks(t).toLowerCase())) {
      k = "al";
    }
    out.push(k);
    prev = k.split(" ").pop();
  }
  return out.join(" ");
}

function wordKey(word) {
  const s = scriptOf(word);
  if (s === "cy") return nameFold(cyKey(word));
  if (s === "la") return nameFold(latinKey(word));
  if (s === "ar") {
    for (const p of AR_ARTICLE) {
      if (word.startsWith(p) && cpLen(word) - cpLen(p) >= 2) return word.slice(p.length);
    }
    return word;
  }
  return word.toLowerCase();
}

function tokens(text) {
  const t = !ARABIC.test(text) ? stripMarks(text).replace(APOS, "") : text;
  return tokenize(normalize(t));
}

/** translit.match_key: lookup key for a whole name (any script). */
export function matchKey(name) {
  let toks = tokens(name);
  if (toks.length > 1 && scriptOf(toks[0]) === "la" && LAT_ARTICLE.has(toks[0])) toks = toks.slice(1);
  return joinKeys(toks, toks.map(wordKey));
}

const AR_SUFFIXES = ["ات", "ون", "ين", "ان", "ها", "هم", "هن", "كم", "نا", "يه", "وا", "ية", "ه", "ة", "ي", "ت"];

function arSuffix(tok) {
  for (const s of AR_SUFFIXES) {
    if (tok.endsWith(s) && cpLen(tok) - cpLen(s) >= 3) return tok.slice(0, tok.length - s.length);
  }
  return tok;
}

const RU_VOW = "аеиоуыэюя";
const RU_PERF1 = ["вшись", "вши", "в"];
const RU_PERF2 = ["ившись", "ывшись", "ивши", "ывши", "ив", "ыв"];
const RU_ADJ = ["ими", "ыми", "его", "ого", "ему", "ому", "ее", "ие", "ые", "ое", "ей", "ий", "ый", "ой", "ем", "им",
  "ым", "ом", "их", "ых", "ую", "юю", "ая", "яя", "ою", "ею"];
const RU_PART1 = ["ем", "нн", "вш", "ющ", "щ"];
const RU_PART2 = ["ивш", "ывш", "ующ"];
const RU_VERB1 = ["ете", "йте", "нно", "ешь", "ла", "на", "ли", "ло", "но", "ет", "ют", "ны", "ть", "ем", "й", "л", "н"];
const RU_VERB2 = ["ейте", "уйте", "ила", "ыла", "ена", "ите", "или", "ыли", "ило", "ыло", "ено", "ует", "уют", "ены",
  "ить", "ыть", "ишь", "ей", "уй", "ил", "ыл", "им", "ым", "ен", "ят", "ит", "ыт", "ую", "ю"];
const RU_NOUN = ["иями", "ями", "ами", "иям", "иях", "ией", "ием", "ие", "ье", "еи", "ии", "ей", "ой", "ий", "ям", "ем",
  "ам", "ом", "ах", "ях", "ию", "ью", "ия", "ья", "ев", "ов", "а", "е", "и", "й", "о", "у", "ы", "ь", "ю", "я"];

// All Cyrillic stemmer input is U+0400-04FF (BMP), so UTF-16 indices equal Python code-point indices here.
function ends(w, rv, group, needAy = false) {
  let best = "";
  for (const e of group) {
    if (e.length > best.length && w.endsWith(e)) {
      const i = w.length - e.length;
      if (i >= rv && (!needAy || (i - 1 >= rv && "ая".includes(w[i - 1])))) best = e;
    }
  }
  return best;
}

function ruStem(w) {
  const n = w.length;
  let rv = n, r1 = n, r2 = n;
  for (let i = 0; i < n; i++) {
    if (RU_VOW.includes(w[i])) { rv = i + 1; break; }
  }
  let seenV = false;
  for (let i = 0; i < n; i++) {
    if (RU_VOW.includes(w[i])) seenV = true;
    else if (seenV) { r1 = i + 1; break; }
  }
  seenV = false;
  for (let i = r1; i < n; i++) {
    if (RU_VOW.includes(w[i])) seenV = true;
    else if (seenV) { r2 = i + 1; break; }
  }
  const cut = (e) => w.slice(0, w.length - e.length);
  let e = ends(w, rv, RU_PERF1, true) || ends(w, rv, RU_PERF2);
  if (e) {
    w = cut(e);
  } else {
    e = ends(w, rv, ["ся", "сь"]);
    if (e) w = cut(e);
    e = ends(w, rv, RU_ADJ);
    if (e) {
      w = cut(e);
      e = ends(w, rv, RU_PART1, true) || ends(w, rv, RU_PART2);
      if (e) w = cut(e);
    } else {
      e = ends(w, rv, RU_VERB1, true) || ends(w, rv, RU_VERB2);
      if (!e) e = ends(w, rv, RU_NOUN);
      if (e) w = cut(e);
    }
  }
  if (w.endsWith("и") && w.length > rv) w = w.slice(0, -1);
  for (const d of ["ость", "ост"]) {
    if (w.endsWith(d) && w.length - d.length >= r2) { w = w.slice(0, w.length - d.length); break; }
  }
  if (w.endsWith("ейше")) w = w.slice(0, -4);
  else if (w.endsWith("ейш")) w = w.slice(0, -3);
  if (w.endsWith("нн")) w = w.slice(0, -1);
  else if (w.endsWith("ь")) w = w.slice(0, -1);
  return w;
}

const UK_ENDINGS = ["ього", "ьому", "ами", "ями", "ові", "еві", "ого", "ому", "ими", "іми", "ати", "яти", "ити", "ють",
  "ять", "ать", "ить", "уть", "ів", "їв", "ий", "ій", "ої", "ою", "ею", "єю", "ем", "єм", "ам", "ям",
  "ах", "ях", "ая", "яя", "ую", "юю", "ає", "яє", "ює", "ує", "ла", "ло", "ли", "а", "я", "у", "ю",
  "е", "є", "и", "ї", "і", "о", "ь", "й"];
const UK_LETTERS = /[іїєґ]/u;

function ukStem(w) {
  for (const r of ["ся", "сь"]) {
    if (w.endsWith(r) && w.length - 2 >= 4) { w = w.slice(0, -2); break; }
  }
  for (const e of UK_ENDINGS) {
    if (w.endsWith(e) && w.length - e.length >= 4) return w.slice(0, w.length - e.length);
  }
  return w;
}

function cyStem(w) {
  let s = UK_LETTERS.test(w) ? ukStem(w) : ruStem(w);
  if (s.length < 4 || s === w) s = w;
  return s;
}

// --------------------------------------------------------------------------- //
// textnorm: FTS5 query building
// --------------------------------------------------------------------------- //

const CYR_WORD_FULL = /^[Ѐ-ӿ]+$/u;

function star(x) {
  return cpLen(x) >= 4 ? `"${x}"*` : `"${x}"`;
}

// Latin-script query stemming (lps U2, textnorm.lat_stem): one inflection-stripped prefix per word
const LAT_WORD_SRC = "[a-zà-ɏ]+";
const LAT_WORD = new RegExp(`^${LAT_WORD_SRC}$`, "u");
const LAT_SUFFIXES = [["ies", "y"], ["ings", ""], ["ing", ""], ["ed", ""], ["es", ""], ["s", ""]];
const MIN_LAT_WORD = 6, MIN_LAT_STEM = 5;
function latStem(w) {
  if (cpLen(w) < MIN_LAT_WORD || !LAT_WORD.test(w)) return w;
  for (const [suf, rep] of LAT_SUFFIXES) {
    if (w.endsWith(suf)) {
      const st = w.slice(0, w.length - suf.length) + rep;
      if (cpLen(st) >= MIN_LAT_STEM) return st;
    }
  }
  return w;
}

function wordForms(w, stem = true) {
  const forms = [`"${w}"*`];
  if (ARABIC_AT0.test(w)) {
    let s = stripPrefix(w);
    if (s !== w && cpLen(w) - cpLen(s) >= 2) forms.push(`"${s}"*`);
    else s = w;
    const x = stem ? arSuffix(s) : s;
    if (x !== s) forms.push(star(x));
  } else if (stem && CYR_WORD_FULL.test(w)) {
    const st = cyStem(w);
    if (st !== w) forms.push(star(st));
  } else if (stem) {
    const st = latStem(w);
    if (st !== w) forms.push(star(st));
  }
  return forms;
}

function ftsWord(w, stem = true) {
  const f = wordForms(w, stem);
  return f.length === 1 ? f[0] : "(" + f.join(" OR ") + ")";
}

const NEAR_RE = /^NEAR(?:\/([0-9]{1,4}))?$/u;
const NEAR_MARK = /^\ue000([0-9]+)\ue001$/u;
const DEFAULT_NEAR = 10;
const SPLIT = new RegExp(`"[^"]*"\\*?|[^${S}]+`, "gu");

function nearOperandExpr(o) {
  if (o.kind === "phrase") return '"' + o.words.join(" ") + '"' + (o.prefix ? "*" : "");
  return '"' + o.words.join(" ") + '"*';
}

function nearExpr(exprs, n) {
  return `NEAR(${exprs.join(" ")}, ${n})`;
}

/** Kept for callers that catch it. Nothing throws it any more: `a OR NEAR b`, which used to raise KeyError in
 * Python (and this error here), now drops the NEAR in both. */
export class LpsQueryError extends Error {
  constructor(pyType, msg) {
    super(msg);
    this.name = "LpsQueryError";
    this.pyType = pyType;
  }
}

function ftsParts(q) {
  const raw = (q || "").match(SPLIT) || [];
  q = pyStrip(normalize(raw.map((p) => {
    const m = !p.startsWith('"') ? NEAR_RE.exec(p) : null;
    return m ? `\ue000${m[1] || DEFAULT_NEAR}\ue001` : p;
  }).join(" ")));
  const out = [];
  for (let p of q.match(SPLIT) || []) {
    if (p.toUpperCase() === "OR") { out.push({ op: "OR" }); continue; }
    const m = NEAR_MARK.exec(p);
    if (m) { out.push({ op: "NEAR", n: Math.min(parseInt(m[1], 10), 1000) }); continue; }
    const neg = p.startsWith("-") && cpLen(p) > 1;
    if (neg) p = p.slice(1);
    const words = tokenize(p);
    if (!words.length) continue;
    if (p.startsWith('"')) {
      out.push({ kind: "phrase", neg, words, expr: '"' + words.join(" ") + '"', prefix: p.endsWith("*") });
    } else {
      const each = words.map((w) => ftsWord(w, !neg));
      out.push({ kind: "word", neg, words, expr: each.length === 1 ? each[0] : "(" + each.join(" AND ") + ")" });
    }
  }
  return foldNear(out);
}

function foldNear(parts) {
  const out = [];
  let i = 0;
  while (i < parts.length) {
    let p = parts[i];
    if (p.op === "NEAR") {
      let prev = out.length ? out[out.length - 1] : null;
      const nxt = i + 1 < parts.length ? parts[i + 1] : null;
      if (prev && nxt && "kind" in nxt && !nxt.neg && nxt.kind !== "near") {
        if (["word", "phrase", "near"].includes(prev.kind) && !prev.neg) {   // an {op} part has no kind: dropped
          if (prev.kind !== "near") {
            out[out.length - 1] = prev = { kind: "near", neg: false, operands: [prev], n: p.n, words: [...prev.words] };
          }
          prev.operands.push(nxt);
          prev.n = Math.max(prev.n, p.n);
          prev.words.push(...nxt.words);
          prev.expr = nearExpr(prev.operands.map(nearOperandExpr), prev.n);
          i += 2;
          continue;
        }
      }
      i += 1;
      continue;
    }
    if (p.kind === "near") p = { ...p, expr: nearExpr(p.operands.map(nearOperandExpr), p.n) };
    out.push(p);
    i += 1;
  }
  for (const p of out) {
    if (p.kind === "near" && !("expr" in p)) p.expr = nearExpr(p.operands.map(nearOperandExpr), p.n);
  }
  return out.filter((p) => p.op !== "NEAR");
}

function andJoin(tokens) {
  const res = [];
  for (const t of tokens) {
    if (res.length && res[res.length - 1] !== "OR" && res[res.length - 1] !== "NOT" && t !== "OR" && t !== "NOT") {
      res.push("AND");
    }
    res.push(t);
  }
  return res;
}

function ftsAssemble(items) {
  const out = [];
  for (const it of items) {
    if (it === "OR") {
      if (out.length && out[out.length - 1] !== "OR") out.push("OR");
      continue;
    }
    const [expr, neg] = it;
    if (neg) {
      if (!out.length || out[out.length - 1] === "OR") continue;
      out.push("NOT");
    }
    out.push(expr);
  }
  while (out.length && (out[out.length - 1] === "OR" || out[out.length - 1] === "NOT")) out.pop();
  return andJoin(out).join(" ") || null;
}

/** textnorm.fts_query: user query -> safe FTS5 expression (literal; null for an empty query). */
export function ftsQuery(q) {
  return ftsAssemble(ftsParts(q).map((p) => ("op" in p ? "OR" : [p.expr, p.neg])));
}

/** textnorm.fts_scoped: restrict to the text columns {norm stems}, the {meta} column, or either. */
export function ftsScoped(expr, text = true, names = false) {
  const parts = [...(text ? ["{norm stems} : (" + expr + ")"] : []), ...(names ? ["{meta} : (" + expr + ")"] : [])];
  return parts.length > 1 ? parts.join(" OR ") : parts.length ? parts[0] : null;
}

// --------------------------------------------------------------------------- //
// lexicon.expand, without a dictionary
// --------------------------------------------------------------------------- //

const MAX_ALTS_TOTAL = 120;
const MAX_NEAR = 24;
const STOPWORDS = new Set(`
about above after again against almost along already also although always another around away back been before
being below between both bring but came can come could dont down during each either else enough even ever every
find first from gave get give goes going gone good great have having here high himself into just keep kept know
last least left less like little long look made make many maybe might more most much must near need never next
none once only onto other otherwise over people place quite rather really right said same saw say see seem seen
several shall should since some someone something soon still such take taken tell than that their them then there
these they thing think this those though three through thus time today together took toward under until upon
used using very want was well went were what when where whether which while whom whose will with within without
would year years yes your yours after amid among because been call called case city town village north south
east west central new old big small large green white black red blue yellow grey gray river lake hill hills
mountain mount valley field fields forest wood woods rock stone bridge road street way home house school church
market station camp base line front force forces army group party news post video photo photos live world state
states country land island port park garden king queen prince lord love hope faith star sun moon light dark night
day week month name word story report says said told asked reported killed killing attack attacks fire fight war
peace free open close green victory freedom liberty union spring summer autumn winter rose lion eagle wolf bear
fox mark john paul peter james jack jean rock hand head face body life death dead deaths dies died alive
`.split(/\s+/).filter(Boolean));

const NO_DICT_STATUS = {
  available: false, key_version_ok: false,
  message: "No place dictionary is installed on this computer: only the words you typed (and their "
    + "Cyrillic spelling key) are searched, not other languages or spellings.",
};

const nk = (name) => pyStrip(normalize(name));

function asList(v) {
  if (typeof v === "string") v = v.split(",");
  return (v || []).filter((x) => x && pyStrip(x)).map(nk);
}

function product(lists) {
  let out = [[]];
  for (const l of lists) {
    const nxt = [];
    for (const pre of out) for (const x of l) nxt.push([...pre, x]);
    out = nxt;
  }
  return out;
}

/**
 * lexicon.expand(q) with no dictionary.db: {enabled, dict_version, fts, groups, dictionary[, near_reduced,
 * near_used]}, same keys in the same order as Python. Options: {enabled = true, drop = [], skip = []} as in
 * lexicon.expand (strings are comma-separated lists).
 */
export function expand(q, { enabled = true, drop = [], skip = [] } = {}) {
  const parts = ftsParts(q);
  const literal = ftsAssemble(parts.map((p) => ("op" in p ? "OR" : [p.expr, p.neg])));
  const exp = { enabled: !!enabled, dict_version: "none", fts: literal, groups: [],
    dictionary: { ...NO_DICT_STATUS } };
  if (!enabled || !literal) return exp;
  let dropSet = new Set(asList(drop));
  const skipSet = new Set(asList(skip));
  dropSet = new Set([...dropSet].filter((x) => !x.startsWith("+")));
  const items = [], groups = [], nearReduced = [];
  let budget = MAX_ALTS_TOTAL;

  function translitGroup(w) {
    const key = scriptOf(w) === "la" ? latinKey(w) : "";
    if (cpLen(w) >= 4 && isAlpha(w) && !STOPWORDS.has(w) && cpLen(key) >= 3 && budget > 0) {
      const term = `Cyrillic ≈ ${key}`;
      const g = { span: w, kind: "translit", label: w, detail: "matches the Cyrillic spelling",
        entries: [], more_entries: 0,
        alts: [{ term, lang: "translit", historic: false, dropped: dropSet.has(nk(term)) }] };
      budget -= 1;
      return [g, [`"${ROMAN_PREFIX}${key}"*`]];
    }
    return null;
  }

  function emit(g, exprs, toks) {
    let orig = toks.map((w) => ftsWord(w));
    orig = orig.length === 1 ? orig[0] : "(" + orig.join(" AND ") + ")";
    if (skipSet.has(g.span)) g.skipped = true;
    const live = g.skipped ? [] : g.alts.map((a, i) => [a, exprs[i]]).filter(([a]) => !a.dropped).map(([, e]) => e);
    items.push([live.length ? "(" + [orig, ...live].join(" OR ") + ")" : orig, false]);
  }

  function flush(run) {
    for (const w of run) {           // no dictionary: no span ever forms a group, every word stands alone
      const got = translitGroup(w);
      if (got) {
        groups.push(got[0]);
        emit(got[0], got[1], [w]);
      } else {
        items.push([ftsWord(w), false]);
      }
    }
  }

  function nearPart(p) {
    const opts = [], labels = [];
    for (const o of p.operands) {
      if (o.kind !== "word" || o.words.length !== 1) {
        opts.push([nearOperandExpr(o)]);
        labels.push([o.words.join(" ")]);
        continue;
      }
      const w = o.words[0];
      let forms = wordForms(w);
      if (forms.length === 2 && CYRILLIC.test(w)) forms = forms.slice(1);
      const cur = forms.map((f) => [f, w]);
      let zz = [];
      const t = translitGroup(w);
      if (t) {
        groups.push(t[0]);
        if (!(skipSet.has(w) || t[0].alts[0].dropped)) zz = [[t[1][0], t[0].alts[0].term]];
      }
      const seen = new Set();
      const allo = [...cur, ...zz].filter((x) => (seen.has(x[0]) ? false : (seen.add(x[0]), true)));
      opts.push(allo.map((x) => x[0]));
      labels.push(allo.map((x) => x[1]));
    }
    let total = 1;
    for (const o of opts) total *= o.length;
    if (total > MAX_NEAR) {
      while (total > MAX_NEAR) {
        let i = 0;
        for (let k = 1; k < opts.length; k++) if (opts[k].length > opts[i].length) i = k;
        total = Math.floor(total / opts[i].length) * (opts[i].length - 1);
        opts[i].pop();
        labels[i].pop();
      }
      const opName = (o) => (o.words.length === 1 ? o.words[0] : o.words.join(" "));
      nearReduced.push({ near: p.operands.map(opName).join(" NEAR "),
        used: p.operands.map((o, k) => ({ operand: opName(o), alts: labels[k] })) });
    }
    const exprs = product(opts).map((c) => nearExpr(c, p.n));
    items.push([exprs.length > 1 ? "(" + exprs.join(" OR ") + ")" : exprs[0], false]);
  }

  let run = [];
  for (const p of parts) {
    if ("op" in p) {
      flush(run); run = [];
      items.push("OR");
    } else if (p.kind === "word" && !p.neg) {
      run.push(...p.words);
    } else if (p.kind === "near") {
      flush(run); run = [];
      nearPart(p);
    } else {
      flush(run); run = [];
      items.push([p.expr, p.neg]);
    }
  }
  flush(run);
  exp.fts = ftsAssemble(items) || literal;
  exp.groups = groups;
  if (nearReduced.length) {
    exp.near_reduced = true;
    exp.near_used = nearReduced;
  }
  return exp;
}

/** Internals, for the parity test only: the hand-copied lps tables, compared one-to-one with Python's. */
function bmpChars(rx) {
  const r = new RegExp(rx.source, "u"), out = [];
  for (let c = 0; c < 0x10000; c++) if (!(c >= 0xd800 && c <= 0xdfff) && r.test(String.fromCharCode(c))) out.push(c);
  return out;
}
export const _internal = {
  TABLES, wordKey, nameFold, joinKeys, scriptOf, cyKey, latinKey, cyStem, latStem, arSuffix, stripPrefix, wordForms, tokens, ftsParts,
  constants: () => ({
    AR_PREFIXES, AR_SUFFIXES, AR_ARTICLE, RU_VOW, RU_PERF1, RU_PERF2, RU_ADJ, RU_PART1, RU_PART2, RU_VERB1,
    RU_VERB2, RU_NOUN, UK_ENDINGS, CY: Object.fromEntries(CY), LAT_MULTI, LAT_ONE: Object.fromEntries(LAT_ONE),
    LAT_ARTICLE: [...LAT_ARTICLE].sort(), LAT_TWINS, CYR_TWINS, TRANS: Object.fromEntries(TRANS),
    STOPWORDS: [...STOPWORDS].sort(), LAT_SUFFIXES, MIN_LAT_WORD, MIN_LAT_STEM, LAT_WORD: LAT_WORD_SRC,
    NAME_FOLDS, ABD_WORDS: [...ABD_WORDS].sort(), ABD_ALLAH, ABD_JOINED, ALLAH, NAME_ARTICLES: [...NAME_ARTICLES].sort(),
    CY_ARTICLE: [...CY_ARTICLE].sort(), MAX_NEAR, MAX_ALTS_TOTAL, DEFAULT_NEAR, NO_DICT_STATUS,
    chars: { AR_MARKS: bmpChars(AR_MARKS), APOS: bmpChars(APOS), SEPS: bmpChars(SEPS), UK_LETTERS: bmpChars(UK_LETTERS),
      ARABIC: bmpChars(ARABIC), CYRILLIC: bmpChars(CYRILLIC), LATIN: bmpChars(LATIN) },
  }),
};
