module.exports = {
  content: ["./src/**/*.{js,ts,tsx}", "./index.html"],
  corePlugins: { preflight: false },
  theme: {
    extend: {
      colors: {
        primary: "var(--p)",
        surface: "var(--surface)",
        muted: "var(--muted)",
        border: "var(--line)",
      },
    },
  },
};
