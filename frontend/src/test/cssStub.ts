// Stub for CSS imports in Vitest — returns an empty module so that
// bare CSS side-effect imports (e.g. @xterm/xterm/css/xterm.css) don't
// cause a transform error in the jsdom environment.
export default {}
